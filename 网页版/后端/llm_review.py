#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""llm_review.py — 外接大模型「二次校验」层（纯标准库，BYOK）

在 party_planner 的确定性算法之上，再加一层大模型校验：
把三档方案 + 预算/人数/可叠优惠 发给用户自选的大模型，让它从
「能不能更省、搭配是否合理、口味/份量是否合适」角度给建议，
帮助用户在算法结果之外再做一次判断。

定位：大模型只给建议，不做价格——最终价格一律以官方 calculate-price
核价为准（换餐品/换券后仍需回 MCP 重新核价）。

协议：OpenAI 兼容的 /chat/completions（DeepSeek / OpenAI / 智谱 GLM /
Moonshot Kimi / 通义千问 等都兼容，只是 base_url 不同）。
API Key 走请求头 X-LLM-Key，只在单次请求内存中使用，不落盘、不写日志。
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request


class LlmError(RuntimeError):
    """大模型调用失败（网络/鉴权/协议/返回异常）。"""


# 预设模型（OpenAI 兼容）。base_url 统一拼 "/chat/completions"。
MODEL_PRESETS = [
    {"id": "deepseek", "label": "DeepSeek（推荐，便宜）",
     "baseUrl": "https://api.deepseek.com/v1", "model": "deepseek-chat"},
    {"id": "openai", "label": "OpenAI GPT",
     "baseUrl": "https://api.openai.com/v1", "model": "gpt-4o-mini"},
    {"id": "zhipu", "label": "智谱 GLM（有免费档）",
     "baseUrl": "https://open.bigmodel.cn/api/paas/v4", "model": "glm-4-flash"},
    {"id": "moonshot", "label": "Moonshot Kimi",
     "baseUrl": "https://api.moonshot.cn/v1", "model": "moonshot-v1-8k"},
    {"id": "qwen", "label": "通义千问",
     "baseUrl": "https://dashscope.aliyuncs.com/compatible-mode/v1", "model": "qwen-plus"},
    {"id": "custom", "label": "自定义（填 base_url + 模型名）", "baseUrl": "", "model": ""},
]


def _endpoint(base_url: str) -> str:
    url = (base_url or "").strip().rstrip("/")
    if not url:
        raise LlmError("缺少大模型 base_url")
    if url.endswith("/chat/completions"):
        return url
    return url + "/chat/completions"


def extract_json(text: str) -> dict:
    """从大模型返回里抽 JSON（可能带 ```json 围栏或前后废话），失败降级为 {raw}。"""
    text = (text or "").strip()
    if not text:
        return {}
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else {"raw": text}
    except json.JSONDecodeError:
        pass
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if m:
        try:
            data = json.loads(m.group(1))
            return data if isinstance(data, dict) else {"raw": text}
        except json.JSONDecodeError:
            pass
    a, b = text.find("{"), text.rfind("}")
    if a >= 0 and b > a:
        try:
            data = json.loads(text[a:b + 1])
            return data if isinstance(data, dict) else {"raw": text}
        except json.JSONDecodeError:
            pass
    return {"raw": text}


def call_llm(base_url: str, model: str, api_key: str, system: str, user: str,
             temperature: float = 0.3, timeout: int = 90) -> str:
    """OpenAI 兼容 chat/completions 非流式调用，返回 message.content 文本。"""
    if not (api_key or "").strip():
        raise LlmError("缺少大模型 API Key")
    if not (model or "").strip():
        raise LlmError("缺少大模型 model 名称")
    payload = {
        "model": model.strip(),
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": temperature,
        "stream": False,
    }
    req = urllib.request.Request(
        _endpoint(base_url),
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": "Bearer " + api_key.strip(),
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")[:300]
        raise LlmError(f"大模型接口 HTTP {e.code}：{detail}") from e
    except urllib.error.URLError as e:
        raise LlmError(f"大模型网络错误：{e.reason}") from e

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        raise LlmError(f"大模型返回非 JSON：{raw[:200]}")

    if isinstance(data, dict) and data.get("error"):
        raise LlmError(f"大模型接口报错：{json.dumps(data['error'], ensure_ascii=False)[:300]}")
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        raise LlmError(f"大模型返回结构异常：{raw[:300]}")
    return content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)


def build_prompt(plans: list, store: dict, people, budget, hints: dict) -> tuple[str, str]:
    """构造 system / user 两条消息。

    plans：三档方案（tier/total/per_person/items/saved/coupon）
    hints：可叠优惠提示（可领未领券、卡包券、活动等）
    """
    system = (
        "你是一名麦当劳团餐点单顾问。用户给你一套已经用麦当劳官方接口真实核价、"
        "并叠好优惠的三档方案（经济型/均衡型/丰盛型）。请你从「能不能更省、"
        "搭配是否合理、口味/份量是否合适、是否贴合预算」角度做二次校验，"
        "给出务实、可执行的建议。"
        "硬规则：你只能给建议，绝不能自己估算价格（价格一律以官方核价为准）；"
        "换餐品/换券后用户会重新用官方接口核价，所以你的建议重点放在『该换什么、"
        "该叠哪张券、哪一档最划算』。"
        "只输出 JSON，不要任何解释文字，结构必须是："
        '{"summary":"一句话总评","suggestions":[{"tier":"经济型","advice":"建议","why":"原因"}],'
        '"overall":"给用户的一句话行动建议"}。'
        "suggestions 里 tier 只能取 经济型/均衡型/丰盛型 或 全部；没有建议的档位可不列。"
    )
    user = json.dumps({
        "门店": store,
        "人数": people,
        "预算": budget,
        "三档方案": plans,
        "优惠提示": hints,
    }, ensure_ascii=False, indent=1)
    return system, user
