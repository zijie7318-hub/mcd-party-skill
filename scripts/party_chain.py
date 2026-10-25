#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""party_chain.py — 麦当劳 MCP 链路编排（纯 Python 标准库，无第三方依赖）

职责：
- 按契约顺序调用 MCP：query-nearby-stores → query-meals → calculate-price
  → query-party-city → query-party-store → query-party-store-date → query-party-store-session
- 滑动窗口节流：每分钟最多 300 次（官方上限 600，留一半余量）
- 仅 HTTP 429 做指数退避重试（1s → 2s → 4s，最多 3 次）；其余失败一律抛异常停止，不自动重试
- 写操作默认 dry_run：只有命令行传入 --confirm 才真实调用
- Token 只从环境变量 MCD_MCP_TOKEN 读取，绝不写死

MCP 传输：Streamable HTTP（JSON-RPC 2.0）。首条 initialize 请求换取
Mcp-Session-Id，后续请求全部携带；响应可能是 JSON 或 SSE，统一解析。
"""

from __future__ import annotations

import argparse
import collections
import json
import os
import sys
import time
import urllib.error
import urllib.request
from typing import Any

_MCP_URL = "https://mcp.mcd.cn"
PROTOCOL_VERSION = "2024-11-05"
CLIENT_INFO = {"name": "mcd-party-skill", "version": "1.0.0"}

# 官方 600 次/分钟，本项目留一半余量
RATE_LIMIT = 300
RATE_WINDOW_SEC = 60.0
BACKOFF_SEQ = (1.0, 2.0, 4.0)  # 仅 429 使用，最多 3 次重试

# 属于"写操作"的 MCP 工具名单：默认 dry_run
WRITE_TOOLS = {
    "create-order", "mall-create-order", "party-order-create",
    "cancel-order", "auto-bind-coupons", "draw-lottery",
}


class McpError(RuntimeError):
    """MCP 调用失败（协议错误/业务错误/网络错误）。429 重试耗尽也归于此。"""


def _require_token() -> str:
    token = os.environ.get("MCD_MCP_TOKEN", "").strip()
    if not token:
        raise McpError("[停止] 环境变量 MCD_MCP_TOKEN 未设置，拒绝继续。")
    return token


class _Throttle:
    """滑动窗口节流器：过去 60 秒内的调用数达到上限时，阻塞到最早一条滑出窗口。"""

    def __init__(self, limit: int = RATE_LIMIT, window: float = RATE_WINDOW_SEC):
        self.limit, self.window = limit, window
        self._hits: collections.deque[float] = collections.deque()

    def acquire(self) -> None:
        now = time.monotonic()
        while self._hits and now - self._hits[0] >= self.window:
            self._hits.popleft()
        if len(self._hits) >= self.limit:
            wait = self.window - (now - self._hits[0]) + 0.01
            sys.stderr.write(f"[节流] 已达 {self.limit} 次/分钟，等待 {wait:.1f}s\n")
            time.sleep(max(wait, 0.0))
            self.acquire()  # 递归一次即可（窗口只会长不会短）
        self._hits.append(time.monotonic())


class McpClient:
    """极简 Streamable HTTP MCP 客户端（JSON-RPC 2.0 over urllib）。"""

    def __init__(self, url: str = _MCP_URL, dry_run: bool = True):
        self.url = url
        self.dry_run = dry_run
        self._throttle = _Throttle()
        self._token = _require_token()
        self._session_id: str | None = None
        self._req_id = 0
        self._initialized = False

    # ---------- HTTP / JSON-RPC 底层 ----------

    def _post(self, payload: dict, expect_reply: bool = True) -> dict | None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "Authorization": f"Bearer {self._token}",
        }
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id

        for attempt, backoff in enumerate((0.0,) + BACKOFF_SEQ):
            self._throttle.acquire()
            req = urllib.request.Request(self.url, data=body, headers=headers, method="POST")
            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    sid = resp.headers.get("Mcp-Session-Id")
                    if sid:
                        self._session_id = sid
                    raw = resp.read().decode("utf-8", errors="replace")
                    return self._parse_body(raw) if expect_reply else {}
            except urllib.error.HTTPError as e:
                if e.code == 429 and attempt < len(BACKOFF_SEQ):
                    sys.stderr.write(f"[429] 指数退避 {backoff:.0f}s 后重试（第 {attempt + 1} 次）\n")
                    time.sleep(backoff)
                    continue
                raise McpError(f"[停止] MCP HTTP {e.code}：{e.reason}（429 重试已耗尽或非 429，不自动重试）") from e
            except urllib.error.URLError as e:
                raise McpError(f"[停止] MCP 网络错误：{e.reason}（不自动重试）") from e
        raise McpError("[停止] 不可达：重试序列耗尽。")

    @staticmethod
    def _parse_body(raw: str) -> dict:
        """响应可能是纯 JSON，也可能是 SSE（多行 data: {...}）。"""
        raw = raw.strip()
        if not raw:
            return {}
        if raw.startswith("{") or raw.startswith("["):
            return json.loads(raw)
        for line in raw.splitlines():
            line = line.strip()
            if line.startswith("data:"):
                data = line[5:].strip()
                if data and data != "[DONE]":
                    return json.loads(data)
        return {}

    def _rpc(self, method: str, params: dict | None = None, notify: bool = False) -> dict | None:
        self._req_id += 1
        payload: dict[str, Any] = {
            "jsonrpc": "2.0", "method": method, "id": None if notify else self._req_id,
        }
        if params is not None:
            payload["params"] = params
        result = self._post(payload, expect_reply=not notify)
        if notify or result is None:
            return None
        if "error" in result and result["error"]:
            raise McpError(f"[停止] MCP 协议错误：{json.dumps(result['error'], ensure_ascii=False)}")
        return result.get("result", {})

    def initialize(self) -> None:
        if self._initialized:
            return
        self._rpc("initialize", {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": CLIENT_INFO,
        })
        self._rpc("notifications/initialized", notify=True)
        self._initialized = True

    # ---------- 工具调用（含 dry_run 闸门） ----------

    def call_tool(self, name: str, arguments: dict | None = None, *, write: bool | None = None) -> dict:
        """调用 MCP 工具。写操作（WRITE_TOOLS 名单或 write=True 显式指定）：
        - dry_run 模式（默认）：不发请求，返回 dry_run 标记
        - --confirm 模式：真实调用
        """
        is_write = write if write is not None else name in WRITE_TOOLS
        if is_write and self.dry_run:
            sys.stderr.write(f"[dry_run] 写操作 {name} 已跳过真实调用（加 --confirm 才会执行）\n")
            return {"dry_run": True, "tool": name, "arguments": arguments or {}}

        self.initialize()
        result = self._rpc("tools/call", {"name": name, "arguments": arguments or {}})
        if result.get("isError"):
            raise McpError(f"[停止] 工具 {name} 业务失败：{json.dumps(result.get('content'), ensure_ascii=False)[:500]}")
        return self._unwrap(result)

    @staticmethod
    def _unwrap(result: dict) -> dict:
        """MCP content 文本块可能是"说明文字 + JSON"混排：先整体解析，
        失败则截取首个 { 到最后一个 } 之间的片段再解析；仍失败返回 raw。"""
        content = result.get("content") or []
        for block in content:
            if block.get("type") == "text":
                text = block.get("text", "").strip()
                # 官方业务响应固定以 {"success"... 开头；混排文本中可能还有
                # 其他花括号片段，因此优先用该锚点截取，再退回首尾截取。
                anchors = [text]
                idx = text.find('{"success"')
                if idx >= 0:
                    anchors.insert(0, text[idx:])
                if "{" in text and "}" in text:
                    anchors.append(text[text.find("{"): text.rfind("}") + 1])
                for candidate in anchors:
                    if not candidate:
                        continue
                    try:
                        data = json.loads(candidate)
                        if isinstance(data, dict):
                            return data
                    except json.JSONDecodeError:
                        continue
                return {"raw": text}
        return {"raw": json.dumps(result, ensure_ascii=False)}

    # ---------- 契约链路封装（顺序固定） ----------

    def query_nearby_stores(self, city: str, keyword: str) -> dict:
        """第 1 步：门店。beType=1 到店自提（无 beCode），searchType=2 按城市+关键词搜索。"""
        return self.call_tool("query-nearby-stores", {
            "searchType": 2, "city": city, "keyword": keyword, "beType": 1,
        })

    def query_meals(self, store_code: str) -> dict:
        """第 2 步：菜单。到店自提 orderType=1 / beType=1，不传 beCode。"""
        return self.call_tool("query-meals", {
            "storeCode": store_code, "orderType": 1, "beType": 1,
        })

    def calculate_price(self, order_args: dict) -> dict:
        """第 3 步：整单核价。任何餐品组合变化都必须重新调用本工具。"""
        return self.call_tool("calculate-price", order_args)

    def _get_party_spu_id(self) -> str:
        """派对前置：从积分商品列表拿一个派对商品 spuId。

        按一号机实测表：需先调 mall-points-products，用 catRuleIds 筛
        "生日类派对 1>6>20 / 主题类派对 1>6>21"，取上架中的常规款。
        """
        resp = self.call_tool("mall-points-products", {
            "catRuleIds": "1>6>20,1>6>21",
        })
        data = resp.get("data") or []
        if isinstance(data, dict):
            data = data.get("list") or data.get("products") or data.get("records") or []
        if not data:
            raise McpError("[停止] 未获取到派对商品 spuId（mall-points-products 为空）。")
        first = data[0]
        spu = first.get("spuId") or first.get("spu_id") or first.get("id") or first.get("productId")
        if spu is None:
            raise McpError(f"[停止] 派对商品缺少 spuId 字段：{json.dumps(first, ensure_ascii=False)[:200]}")
        return str(spu)

    def query_party_chain(self, city: str, store_code: str) -> dict:
        """第 4~7 步：派对四级串联（含 spuId 前置）。任一级失败抛异常（失败即停）。

        实测确定的入参（见工具实测表）：
        1. mall-points-products → spuId
        2. query-party-city(spuId) → 城市 code/latitude/longitude
        3. query-party-store(code, latitude, longitude, spuId) → 门店 code
        4. query-party-store-date(storeCode=门店code, spuId) → date
        5. query-party-store-session(storeCode, dateStr=date, spuId) → 场次
        """
        out: dict[str, Any] = {}
        spu_id = self._get_party_spu_id()
        out["spuId"] = spu_id

        city_resp = self.call_tool("query-party-city", {"spuId": spu_id})
        out["city"] = city_resp
        cities = city_resp.get("data") or []
        if isinstance(cities, dict):
            cities = cities.get("list") or cities.get("cities") or []
        if not cities:
            raise McpError("[停止] query-party-city 未返回城市列表。")
        target = cities[0]
        code = target.get("code")
        latitude = target.get("latitude")
        longitude = target.get("longitude")

        out["store"] = self.call_tool("query-party-store", {
            "code": code, "latitude": latitude, "longitude": longitude, "spuId": spu_id,
        })

        # 门店编码字段名是 code（实测），作为下一步 storeCode 传入
        store_data = out["store"].get("data") or []
        if isinstance(store_data, dict):
            store_data = store_data.get("list") or store_data.get("stores") or []
        party_store_code = None
        if store_data:
            party_store_code = store_data[0].get("code") or store_code
        else:
            party_store_code = store_code
        out["date"] = self.call_tool("query-party-store-date", {
            "storeCode": party_store_code, "spuId": spu_id,
        })

        # 日期返回字段名是 date（实测），传给 session 时入参名是 dateStr
        date_data = out["date"].get("data") or []
        if isinstance(date_data, dict):
            date_data = date_data.get("list") or date_data.get("dates") or []
        if not date_data:
            raise McpError("[停止] 该门店无可用派对日期（data 为空）。")
        date_str = date_data[0].get("date")
        if not date_str:
            raise McpError("[停止] 派对日期缺少 date 字段。")

        out["session"] = self.call_tool("query-party-store-session", {
            "storeCode": party_store_code, "dateStr": date_str, "spuId": spu_id,
        })
        return out


def main() -> int:
    ap = argparse.ArgumentParser(description="麦当劳 MCP 链路编排（契约顺序）")
    ap.add_argument("--city", default="上海")
    ap.add_argument("--keyword", default="人民广场", help="门店搜索关键词（地标/路名）")
    ap.add_argument("--confirm", action="store_true", help="显式确认后，写操作才真实调用（默认 dry_run）")
    ap.add_argument("--skip-party", action="store_true", help="跳过派对四级链路")
    args = ap.parse_args()

    client = McpClient(dry_run=not args.confirm)
    try:
        stores = client.query_nearby_stores(args.city, args.keyword)
        data = stores.get("data") or []
        if not data:
            raise McpError(f"[停止] {args.city} 未查到门店，本轮结束。")
        store = data[0]
        print(f"[1/3] 门店 OK：{store.get('storeName')}（storeCode={store.get('storeCode')}）")

        meals = client.query_meals(str(store["storeCode"]))
        cats = (meals.get("data") or {}).get("categories") or []
        print(f"[2/3] 菜单 OK：{len(cats)} 个分类")

        if not args.skip_party:
            party = client.query_party_chain(args.city, str(store["storeCode"]))
            print(f"[3/3] 派对链路 OK：{list(party.keys())}")

        print("[完成] 链路全通。方案组装请运行 party_planner.py")
        return 0
    except McpError as e:
        print(str(e), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
