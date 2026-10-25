#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""demo_data.py — 把 party_planner 的真实运行结果转成试玩页演示快照 data.js。

用法：
  # 方式一：直接跑一次真实链路，把结果写成 data.js
  python scripts/demo_data.py --city 上海 --keyword 人民广场 --people 4 --budget 120 --out docs/data.js

  # 方式二：把已有的 plan.json 转成 data.js
  python scripts/demo_data.py --from plan.json --out docs/data.js

产物 data.js 内容为 window.DEMO_DATA = {...}，并注入 generated_at 与 note 字段，
供 docs/index.html（免 Token 试玩页）直接加载。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from party_planner import plan  # noqa: E402


def to_demo_js(result: dict) -> str:
    """把 plan() 的输出包装成 window.DEMO_DATA，并补时间戳/说明字段。"""
    payload = dict(result)
    payload["generated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    payload.setdefault("note", "本数据为演示快照，非实时价格；实时价格请以运行时 calculate-price 核价结果为准")
    return "// 由 demo_data.py 生成于真实链路运行结果（含 generated_at / note 字段）\n" \
           "window.DEMO_DATA = " + json.dumps(payload, ensure_ascii=False, indent=2) + ";\n"


def main() -> int:
    ap = argparse.ArgumentParser(description="生成试玩页演示数据 data.js")
    ap.add_argument("--city", default="上海")
    ap.add_argument("--keyword", default="人民广场")
    ap.add_argument("--people", type=int, default=4)
    ap.add_argument("--budget", type=float, default=120)
    ap.add_argument("--taste", default="随便", choices=["随便", "鸡肉", "牛肉"])
    ap.add_argument("--from", dest="from_json", default=None, help="从已有 plan.json 转换（不跑真实链路）")
    ap.add_argument("--out", default="docs/data.js", help="输出 data.js 路径")
    ap.add_argument("--confirm", action="store_true", help="透传（本脚本链路只读，dry_run 不影响查询）")
    args = ap.parse_args()

    if args.from_json:
        result = json.loads(Path(args.from_json).read_text(encoding="utf-8"))
    else:
        result = plan(args.city, args.keyword, args.people, args.budget, args.taste,
                      args.confirm, None)

    js = to_demo_js(result)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(js, encoding="utf-8")
    print(f"[完成] 已写入 {out_path}（{len(js)} 字节）", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
