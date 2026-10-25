#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""麦门聚餐管家 · 网页版后端

把已有的 party_chain.py（MCP 客户端）和 party_planner.py（方案组装）
包成 3 个 HTTP 接口，供 GitHub Pages 前端调用。

用法：
  pip install -r requirements.txt
  export MCD_MCP_TOKEN=你的Token   # Windows PowerShell: $env:MCD_MCP_TOKEN="你的Token"
  python app.py
  然后访问 http://localhost:5000/api/stores?city=西安&keyword=钟楼
"""

import os
import sys
from pathlib import Path

# 让 app.py 能 import 同目录（或上级 scripts/）的 party_chain / party_planner
HERE = Path(__file__).resolve().parent
for p in (HERE, HERE / "scripts", HERE.parent / "scripts"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from flask import Flask, request, jsonify
from flask_cors import CORS

from party_chain import McpClient, McpError
from party_planner import (collect_pool, build_candidate, price_combo, TIERS,
                           collect_coupons, best_tier_price)

app = Flask(__name__)
CORS(app)  # 允许 GitHub Pages 跨域调用


def _err(e):
    return jsonify({"success": False, "error": str(e)}), 500


def _get_token():
    """优先取前端自带的 Token（header X-MCD-Token 或 query token），否则回退后端环境变量。"""
    token = request.headers.get("X-MCD-Token", "") or request.args.get("token", "")
    token = (token or "").strip()
    if token:
        return token
    return os.environ.get("MCD_MCP_TOKEN", "").strip()


@app.route("/api/stores")
def stores():
    city = request.args.get("city", "")
    keyword = request.args.get("keyword", "")
    if not city or not keyword:
        return jsonify({"success": False, "error": "缺少 city 或 keyword 参数"}), 400
    token = _get_token()
    if not token:
        return jsonify({"success": False, "error": "请填写你的麦当劳 MCP Token（open.mcd.cn/mcp 激活获取）"}), 400
    try:
        client = McpClient(dry_run=True, token=token)
        resp = client.query_nearby_stores(city, keyword)
    except McpError as e:
        return _err(e)
    data = resp.get("data") or []
    if isinstance(data, dict):
        data = data.get("list") or data.get("stores") or []
    stores = [{
        "storeCode": s.get("storeCode"),
        "storeName": s.get("storeName"),
        "address": s.get("address"),
        "distance": s.get("distance"),
    } for s in data]
    return jsonify({"success": True, "stores": stores})


@app.route("/api/plans")
def plans():
    store_code = request.args.get("storeCode", "")
    store_name = request.args.get("storeName", "")
    store_address = request.args.get("storeAddress", "")
    people = int(request.args.get("people", 4))
    budget = float(request.args.get("budget", 120))
    taste = request.args.get("taste", "随便")
    if not store_code:
        return jsonify({"success": False, "error": "缺少 storeCode 参数"}), 400
    token = _get_token()
    if not token:
        return jsonify({"success": False, "error": "请填写你的麦当劳 MCP Token（open.mcd.cn/mcp 激活获取）"}), 400
    client = McpClient(dry_run=True, token=token)
    try:
        meals = client.query_meals(store_code)
        pool = collect_pool(meals)
        # Step 3.5：查可叠加优惠（任何一项失败都降级为空，不影响主流程）
        coupons = collect_coupons(client, store_code)
    except McpError as e:
        return _err(e)
    plans_out, skipped = [], []
    for tier in TIERS:
        combo = build_candidate(tier, people, pool, taste)
        if not combo:
            skipped.append(tier)
            continue
        try:
            # Step 4：基准核价 + 逐券试算，取最省（官方核价说了算）
            best = best_tier_price(client, store_code, combo, coupons["store"], budget)
        except McpError:
            skipped.append(tier)
            continue
        plan = {
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
            plan["coupon"] = best["coupon"]
        if best["note"]:
            plan["note"] = best["note"]
        plans_out.append(plan)
    resp = {
        "success": True,
        "plans": plans_out,
        "couponHints": {
            "storeCount": len(coupons["store"]),
            "wallet": coupons["wallet"][:5],
            "claimable": coupons["claimable"][:5],
            "campaigns": coupons["campaigns"][:3],
            "errors": coupons["errors"],
        },
    }
    if store_name or store_address:
        resp["store"] = {"name": store_name, "address": store_address}
    if skipped:
        resp["skippedTiers"] = skipped
    return jsonify(resp)


@app.route("/api/create-order", methods=["POST"])
def create_order():
    body = request.get_json(silent=True) or {}
    store_code = body.get("storeCode")
    items = body.get("items") or []
    take_way = body.get("takeWayCode", "take-in-store")
    if not store_code or not items:
        return jsonify({"success": False, "error": "缺少 storeCode 或 items"}), 400
    # 建单是写操作，用 dry_run=False 真实调用（用户已明确要下单）
    token = _get_token()
    if not token:
        return jsonify({"success": False, "error": "请填写你的麦当劳 MCP Token（open.mcd.cn/mcp 激活获取）"}), 400
    try:
        client = McpClient(dry_run=False, token=token)
        resp = client.call_tool("create-order", {
            "storeCode": store_code,
            "orderType": 1,
            "beType": 1,
            "takeWayCode": take_way,
            "items": [{"productCode": i.get("productCode"), "quantity": i.get("quantity", 1)} for i in items],
        })
    except McpError as e:
        return _err(e)
    data = resp.get("data") or resp
    order = {
        "orderId": data.get("orderId") or data.get("orderNo") or data.get("id"),
        "payUrl": data.get("payUrl") or data.get("payLink") or data.get("payQrCode"),
        "price": data.get("price"),
    }
    return jsonify({"success": True, "order": order})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
