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


# ---------- 优惠叠加（SKILL v1.1.0 Step 3.5 / Step 4，实测口径） ----------
# 实测结论（2026-10-25，西安钟鼓楼广场餐厅）：
# 1. 用券姿势：couponId/couponCode 挂在单个 item 上；同单只能挂一张券，多券同单 price 返回 null
# 2. 券价不随数量缩放：美式中杯×1 与 ×4 带券均为 1330 分（discount=570），增补件 qty=1 即可
# 3. 券适用餐品可能不在门店菜单里（券后价商品，如美式中杯 9900000119），需增补进方案
# 4. 无券单核增补件计价为 0（服务端口径），因此 saved 一律用官方 discount 前后差计算

def _coupon_items(resp: dict) -> list[dict]:
    """query-store-coupons 的 data[] 归一化：只保留有 couponId 且有适用餐品的券。"""
    data = resp.get("data") or []
    if isinstance(data, dict):
        data = data.get("list") or data.get("coupons") or []
    out = []
    for c in data:
        products = [
            {"code": str(p.get("productCode") or ""), "name": _clean(p.get("productName") or "")}
            for p in (c.get("products") or [])
        ]
        products = [p for p in products if p["code"]]
        if c.get("couponId") and products:
            out.append({
                "title": _clean(c.get("title") or "未命名优惠"),
                "couponId": str(c["couponId"]),
                "couponCode": str(c.get("couponCode") or ""),
                "products": products,
            })
    return out


def _parse_wallet(raw: str) -> list[dict]:
    """query-my-coupons 返回 Markdown：'## 标题' + '¥xx.x (用券价格)'。"""
    import re
    wallet = []
    for m in re.finditer(r"##\s*(.+?)\n(.*?)(?=\n##\s|\Z)", raw or "", re.S):
        title = _clean(m.group(1))
        if not title:
            continue
        pm = re.search(r"¥\s*([\d.]+)\s*\(用券价格\)", m.group(2))
        wallet.append({"title": title, "price": float(pm.group(1)) if pm else None})
    return wallet


def _parse_titles(raw: str, pattern: str) -> list[str]:
    """从 Markdown 里按正则抓标题（去重保序）。"""
    import re
    seen, out = set(), []
    for m in re.finditer(pattern, raw or ""):
        t = _clean(m.group(1))
        if t and t not in seen:
            seen.add(t)
            out.append(t)
    return out


def collect_coupons(client: McpClient, store_code: str) -> dict:
    """Step 3.5：把当前能叠的优惠查全（门店券/卡包/可领未领/活动日历）。

    四个查询全部只读；任何一项失败都降级为空并记录原因，不影响主流程
    （券查不到就出无券方案，绝不因为优惠查询失败而整个方案都出不来）。
    """
    out: dict[str, Any] = {"store": [], "wallet": [], "claimable": [], "campaigns": [], "errors": []}
    try:
        out["store"] = _coupon_items(client.query_store_coupons(store_code))
    except McpError as e:
        out["errors"].append(f"门店券查询失败：{e}")
    try:
        out["wallet"] = _parse_wallet(client.query_my_coupons().get("raw") or "")
    except McpError as e:
        out["errors"].append(f"卡包查询失败：{e}")
    try:
        out["claimable"] = _parse_titles(
            client.available_coupons().get("raw") or "", r"优惠券标题：\s*([^\\\n]+)")
    except McpError as e:
        out["errors"].append(f"可领券查询失败：{e}")
    try:
        out["campaigns"] = _parse_titles(
            client.campaign_calendar().get("raw") or "", r"\*\*活动标题\*\*：\s*([^\n]+)")
    except McpError as e:
        out["errors"].append(f"活动日历查询失败：{e}")
    return out


def _price_items(client: McpClient, store_code: str, items: list[dict]) -> dict:
    """带券挂载的整单核价。item 可带 couponId/couponCode（实测只认 item 级）。

    返回 {total, discount, productList}；总价缺失/为 null/非正数都算失败（抛异常），
    避免把服务端的 null/0 当成有效价格。
    """
    resp = client.calculate_price({
        "storeCode": store_code,
        "orderType": 1,
        "beType": 1,
        "items": [
            {"productCode": it["code"], "quantity": it["qty"],
             **({"couponId": it["couponId"], "couponCode": it["couponCode"]}
                if it.get("couponId") else {})}
            for it in items
        ],
    })
    data = resp.get("data") or resp
    total = None
    for key in ("price", "productPrice", "totalPrice", "total"):
        if data.get(key) is not None:
            total = round(_f(data[key]) / 100.0, 2)
            break
    if not total or total <= 0:
        raise McpError(f"[停止] 核价未返回有效总价：{json.dumps(resp, ensure_ascii=False)[:200]}")
    take_way_list = data.get("takeWayList") or []
    take_way_code = take_way_list[0].get("code") if isinstance(take_way_list, list) and take_way_list else None
    return {"total": total, "discount": data.get("discount") or 0,
            "productList": data.get("productList") or [], "takeWayCode": take_way_code}


def _coupon_detail(priced: dict, coupon: dict, product_code: str) -> dict:
    """从核价返回的 productList 里取该券适用商品的 原价→券后价，用于展示。"""
    detail = {"title": coupon["title"], "item": coupon["products"][0]["name"] or coupon["title"]}
    for p in priced.get("productList") or []:
        if str(p.get("productCode")) == product_code:
            before = p.get("originalSubtotal")
            after = p.get("subtotal")
            if before is not None and after is not None:
                detail["before"] = round(_f(before) / 100.0, 2)
                detail["after"] = round(_f(after) / 100.0, 2)
            break
    return detail


def best_tier_price(client: McpClient, store_code: str, combo: list[dict],
                    coupons: list[dict], budget: float) -> dict:
    """Step 4：基准核价 → 逐券试算（同单一张券）→ 按规则取最优。

    两种用券方式（都可与基准对比，官方核价说了算）：
    - in-combo：券适用餐品已在方案里 → 挂券重核，总价只降不升（纯赚，优先采纳）
    - added   ：券适用餐品不在方案里 → 增补 1 件券后价商品，仅当总价仍不超预算才采纳

    返回 {total, saved, coupon, items, note}；saved = 官方 discount 前后差（分→元），
    与 SKILL Schema「原价合计 − 叠加后总价」口径一致（实测记录：美式 19→13.3 省 5.70）。
    """
    base = _price_items(client, store_code, combo)
    base_discount = base["discount"] or 0
    best: dict[str, Any] = {"total": base["total"], "saved": 0.0, "coupon": None,
                            "items": [dict(it) for it in combo], "note": ""}
    incombo_best = None   # 挂券即降的最优解
    added_best = None     # 增补件的最优解（比 saved）

    for c in coupons:
        codes = {p["code"] for p in c["products"]}
        # 变体 1：适用餐品已在方案中 → 挂券重核
        if any(it["code"] in codes for it in combo):
            variant = [dict(it) for it in combo]
            for it in variant:
                if it["code"] in codes:
                    it["couponId"], it["couponCode"] = c["couponId"], c["couponCode"]
            try:
                priced = _price_items(client, store_code, variant)
            except McpError:
                continue
            if priced["total"] < base["total"] and (incombo_best is None or priced["total"] < incombo_best["total"]):
                incombo_best = {
                    "total": priced["total"],
                    "saved": round((priced["discount"] - base_discount) / 100.0, 2),
                    "coupon": _coupon_detail(priced, c, next(p["code"] for p in c["products"])),
                    "items": variant, "note": "",
                }
            continue
        # 变体 2：增补 1 件券后价商品（qty=1 即享券价）
        add = c["products"][0]
        variant = [dict(it) for it in combo] + [{
            "code": add["code"], "name": add["name"] or c["title"], "qty": 1,
            "couponId": c["couponId"], "couponCode": c["couponCode"], "viaCoupon": True,
        }]
        try:
            priced = _price_items(client, store_code, variant)
        except McpError:
            continue
        saved = round((priced["discount"] - base_discount) / 100.0, 2)
        if priced["total"] <= budget and saved > 0 and (added_best is None or saved > added_best["saved"]):
            added_best = {
                "total": priced["total"],
                "saved": saved,
                "coupon": _coupon_detail(priced, c, add["code"]),
                "items": variant, "note": "",
            }

    if incombo_best is not None:
        best = incombo_best
    elif added_best is not None:
        best = added_best
    elif coupons:
        # 查到了券但一张都用上：透明说明原因，不假装用了券
        best["note"] = (f"查到 {len(coupons)} 张可用券，但用上会超预算或与当前餐品不匹配，"
                        "本档按无券方案出（可领未领的券请到 App 领取后再来）")
    best["takeWayCode"] = base.get("takeWayCode")  # 取餐方式（建单用），三档一致
    return best


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

    # Step 3.5：查可叠加优惠（失败降级为空，不影响主流程）
    coupons = collect_coupons(client, store_code)
    print(f"[优惠] 门店券 {len(coupons['store'])} 张 · 卡包 {len(coupons['wallet'])} 张 · "
          f"可领未领 {len(coupons['claimable'])} 张", file=sys.stderr)

    plans: list[dict] = []
    skipped: list[str] = []
    for tier in TIERS:
        combo = build_candidate(tier, people, pool, taste)
        if not combo:
            skipped.append(tier)
            continue
        try:
            best = best_tier_price(client, store_code, combo, coupons["store"], budget)
        except McpError as e:
            sys.stderr.write(f"[停止] {tier} 核价失败，本档跳过：{e}\n")
            skipped.append(tier)
            continue
        plan_item = {
            "tier": tier,
            "total": best["total"],
            "per_person": round(best["total"] / people, 2),
            "over_budget": best["total"] > budget,
            "saved": best["saved"],
            "items": [
                {"name": it["name"], "qty": it["qty"], "viaCoupon": bool(it.get("viaCoupon"))}
                for it in best["items"]
            ],
        }
        if best["coupon"]:
            plan_item["coupon"] = best["coupon"]
        if best["note"]:
            plan_item["note"] = best["note"]
        plans.append(plan_item)
        saved_txt = f"，叠券省 ¥{best['saved']}" if best["saved"] else ""
        coupon_txt = f"（{best['coupon']['title']}）" if best["coupon"] else ""
        print(f"[核价] {tier}：¥{best['total']}（人均 ¥{round(best['total'] / people, 2)}）"
              f"{saved_txt}{coupon_txt}", file=sys.stderr)

    result = {
        "store": {"name": _clean(store.get("storeName", "")), "address": _clean(store.get("address", ""))},
        "people": people,
        "budget": budget,
        "plans": plans,          # 只包含已真实核价的档位；失败的档位不猜价、不出现在结果里
        "party": probe_party(client, city, store_code),
        "couponHints": {
            "storeCount": len(coupons["store"]),
            "wallet": coupons["wallet"][:5],
            "claimable": coupons["claimable"][:5],
            "campaigns": coupons["campaigns"][:3],
            "errors": coupons["errors"],
        },
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
