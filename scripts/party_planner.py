#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""party_planner.py — 方案组装 + 真实核价 + 契约渲染（纯标准库）

流程：
1. 经 party_chain.McpClient 查门店 → 拉真实菜单
2. 按 经济型/均衡型/丰盛型 从真实菜单组装候选组合（避开随单购优惠商品）
3. 每套组合调用 calculate-price 做整单真实核价——换任何餐品都重新核价，
   绝不用菜单显示价加减（total 一律取核价返回）
4. 输出严格符合 CONTRACT.md 契约 Schema 的 JSON：store/people/budget/plans/party
5. 失败即停本轮：保留已成功核价的方案，未核价的档位明确标注跳过，绝不猜价

用法：
  export MCD_MCP_TOKEN=xxx
  python party_planner.py --city 上海 --keyword 人民广场 --people 4 --budget 120 \
      [--taste 鸡肉|牛肉|随便] [--out plan.json] [--confirm]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # 允许直接 python scripts/party_planner.py
from party_chain import McpClient, McpError  # noqa: E402

TIERS = ("经济型", "均衡型", "丰盛型")
TASTE_KEYWORDS = {
    "鸡肉": ("鸡腿", "麦辣", "鸡", "板烧"),
    "牛肉": ("牛肉", "巨无霸", "安格斯", "吉士", "牛"),
}


def _f(v) -> float:
    """菜单价格是字符串（'34.5'），统一转 float。"""
    return float(str(v))


def _clean(name: str) -> str:
    return (name or "").strip()


def collect_pool(meals_resp: dict) -> dict[str, list[dict]]:
    """把真实菜单整理成三档素材池：mains（主食）/ sides（小食）/ drinks（饮品）/ platters（多人餐）。

    硬规则：discountType 非 null 的商品（促销/随单购麦金卡等）全部剔除，
    避免菜单价与核价口径不一致。
    """
    data = meals_resp.get("data") or {}
    meals_map = data.get("meals") or {}
    pool: dict[str, list[dict]] = {"mains": [], "sides": [], "drinks": [], "platters": []}

    for cat in data.get("categories") or []:
        cat_name = _clean(cat.get("name", ""))
        for ref in cat.get("meals") or []:
            code = ref.get("code")
            detail = meals_map.get(code)
            if not detail or detail.get("discountType"):
                continue  # 随单购/促销价商品剔除，价格口径必须干净
            item = {"code": code, "name": _clean(detail.get("name")), "price": _f(detail["currentPrice"])}
            tags = [str(t) for t in (ref.get("tags") or [])]
            if "套餐" in tags or "单人餐" in cat_name or "多人餐" in cat_name:
                pool["platters" if "多人餐" in cat_name else "mains"].append(item)
            elif cat_name.startswith("饮品") or "冷饮" in tags or "热饮" in tags:
                pool["drinks"].append(item)
            elif "小食" in tags:
                # 严格按 tags["小食"] 判定：该分类下还有周边玩具（如联名帽子/贴纸），
                # 只看分类名会把非食品混进素材池，必须排除
                pool["sides"].append(item)
    for key in pool:
        pool[key].sort(key=lambda x: x["price"])
    return pool


def pick_by_taste(items: list[dict], taste: str) -> dict | None:
    """按口味偏好挑主食：优先命中关键词，否则取最便宜。"""
    if not items:
        return None
    for kw in TASTE_KEYWORDS.get(taste, ()):
        for it in items:
            if kw in it["name"]:
                return it
    return items[0]


def build_candidate(tier: str, people: int, pool: dict, taste: str) -> list[dict] | None:
    """确定性组装一个候选组合（qty 随人数）。返回 None 表示该档素材不足。"""
    main = pick_by_taste(pool["mains"] or pool["platters"], taste)
    if main is None:
        return None
    items = [{"code": main["code"], "name": main["name"], "qty": people}]
    if pool["sides"]:
        side = pool["sides"][0] if tier == "经济型" else pool["sides"][-1]
        items.append({"code": side["code"], "name": side["name"], "qty": people})
    if tier != "经济型" and pool["drinks"]:
        drink = pool["drinks"][0]
        items.append({"code": drink["code"], "name": drink["name"], "qty": people})
    if tier == "丰盛型" and len(pool["mains"]) > 1:
        second = pool["mains"][1] if pool["mains"][0] is not main else (pool["mains"][-1] if len(pool["mains"]) > 1 else None)
        if second and second["code"] != main["code"]:
            items.append({"code": second["code"], "name": second["name"], "qty": people})
    if tier == "丰盛型" and pool["platters"]:
        platter = pool["platters"][0]
        items.append({"code": platter["code"], "name": platter["name"], "qty": 1})
    return items


def price_combo(client: McpClient, store_code: str, combo: list[dict]) -> float:
    """整单真实核价：calculate-price 的返回就是唯一价格来源。失败抛异常，不猜价。"""
    resp = client.calculate_price({
        "storeCode": store_code,
        "orderType": 1,
        "beType": 1,
        "items": [{"productCode": it["code"], "quantity": it["qty"]} for it in combo],
    })
    # 核价返回 data.price / data.productPrice，单位为【分】（如 10720 = ¥107.20）
    data = resp.get("data") or resp
    for key in ("price", "productPrice", "totalPrice", "total"):
        if key in data:
            return round(_f(data[key]) / 100.0, 2)
    raise McpError(f"[停止] calculate-price 返回中找不到总价字段：{json.dumps(resp, ensure_ascii=False)[:300]}")


def probe_party(client: McpClient, city: str, store_code: str) -> dict:
    """派对四级串联。任一级失败→按契约输出"暂无派对场次"（点单方案不受影响）。"""
    try:
        chain = client.query_party_chain(city, store_code)
        session = chain.get("session") or {}
        sdata = session.get("data") or session
        sessions = sdata if isinstance(sdata, list) else sdata.get("sessions") or sdata.get("data") or []
        if sessions:
            return {"bookable": True, "note": f"可预订派对，共 {len(sessions)} 个场次可选"}
        return {"bookable": False, "note": "该门店暂无派对场次"}
    except McpError as e:
        sys.stderr.write(f"[提示] 派对链路失败，按契约降级：{e}\n")
        return {"bookable": False, "note": "该门店暂无派对场次"}


def plan(city: str, keyword: str, people: int, budget: float, taste: str,
         confirm: bool, out_path: str | None) -> dict:
    client = McpClient(dry_run=not confirm)

    stores = client.query_nearby_stores(city, keyword)
    store_list = stores.get("data") or []
    if not store_list:
        raise McpError(f"[停止] {city} 未查到门店，本轮结束，保留空结果。")
    store = store_list[0]
    store_code = str(store["storeCode"])
    print(f"[门店] {store.get('storeName')}（{store_code}）", file=sys.stderr)

    meals = client.query_meals(store_code)
    pool = collect_pool(meals)
    print(f"[菜单] mains={len(pool['mains'])} sides={len(pool['sides'])} "
          f"drinks={len(pool['drinks'])} platters={len(pool['platters'])}", file=sys.stderr)

    plans: list[dict] = []
    skipped: list[str] = []
    for tier in TIERS:
        combo = build_candidate(tier, people, pool, taste)
        if not combo:
            skipped.append(tier)
            continue
        try:
            total = price_combo(client, store_code, combo)
        except McpError as e:
            sys.stderr.write(f"[停止] {tier} 核价失败，本档跳过：{e}\n")
            skipped.append(tier)
            continue
        plans.append({
            "tier": tier,
            "total": total,
            "per_person": round(total / people, 2),
            "over_budget": total > budget,
            "items": [{"name": it["name"], "qty": it["qty"]} for it in combo],
        })
        print(f"[核价] {tier}：¥{total}（人均 ¥{round(total / people, 2)}）", file=sys.stderr)

    result = {
        "store": {"name": _clean(store.get("storeName", "")), "address": _clean(store.get("address", ""))},
        "people": people,
        "budget": budget,
        "plans": plans,          # 只包含已真实核价的档位；失败的档位不猜价、不出现在结果里
        "party": probe_party(client, city, store_code),
    }
    if skipped:
        result["skipped_tiers"] = skipped  # 透明披露哪些档位因失败未出方案

    payload = json.dumps(result, ensure_ascii=False, indent=2)
    if out_path:
        Path(out_path).write_text(payload, encoding="utf-8")
        print(f"[完成] 方案已写入 {out_path}", file=sys.stderr)
    else:
        print(payload)
    return result


def main() -> int:
    ap = argparse.ArgumentParser(description="聚会团餐三档方案生成（真实核价）")
    ap.add_argument("--city", required=True)
    ap.add_argument("--keyword", default="人民广场")
    ap.add_argument("--people", type=int, required=True)
    ap.add_argument("--budget", type=float, required=True)
    ap.add_argument("--taste", default="随便", choices=["随便", "鸡肉", "牛肉"])
    ap.add_argument("--out", default=None, help="结果 JSON 输出路径（缺省打印 stdout）")
    ap.add_argument("--confirm", action="store_true", help="透传给 McpClient；本脚本链路全为只读，dry_run 不影响查询")
    args = ap.parse_args()

    if args.people <= 0 or args.budget <= 0:
        print("[停止] people/budget 必须为正数", file=sys.stderr)
        return 2
    try:
        plan(args.city, args.keyword, args.people, args.budget, args.taste,
             args.confirm, args.out)
        return 0
    except McpError as e:
        print(str(e), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
