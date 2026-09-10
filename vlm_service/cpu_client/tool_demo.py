#!/usr/bin/env python3
"""Read-only DEMO business tool: model proposes, CPU validates and executes."""

import argparse
import json
import os
from pathlib import Path
import re
import sys

from client import VlmClient


TOOLS = [{"type": "function", "function": {
    "name": "get_order_status",
    "description": "查询示例订单状态。订单状态必须通过此工具获取，不可猜测。仅含演示数据，不连接真实业务系统。",
    "parameters": {
        "type": "object",
        "properties": {"order_id": {"type": "string", "description": "订单编号，例如 DEMO-1001"}},
        "required": ["order_id"],
        "additionalProperties": False,
    },
}}]


def execute_readonly_tool(call):
    if call.get("type") != "function" or call.get("function", {}).get("name") != "get_order_status":
        raise ValueError("tool is not allowlisted")
    arguments = json.loads(call["function"]["arguments"])
    if not isinstance(arguments, dict) or set(arguments) != {"order_id"}:
        raise ValueError("tool arguments must contain only order_id")
    order_id = arguments["order_id"]
    if not isinstance(order_id, str) or not re.fullmatch(r"DEMO-\d{4}", order_id):
        raise ValueError("invalid demonstration order id")
    # Replace this read-only fixture with an authenticated business API adapter later.
    demo_orders = {"DEMO-1001": "ready_to_ship", "DEMO-1002": "delivered"}
    return {"order_id": order_id, "status": demo_orders.get(order_id, "not_found"), "source": "demo"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path(__file__).with_name("config.example.json"))
    parser.add_argument("--order-id", default="DEMO-1001")
    args = parser.parse_args()
    if not re.fullmatch(r"DEMO-\d{4}", args.order_id):
        raise ValueError("use a demonstration order id such as DEMO-1001")
    cfg = json.loads(args.config.read_text(encoding="utf-8"))
    ca_file = os.getenv("GPU_CA_FILE", cfg.get("ca_file"))
    if ca_file:
        ca_file = args.config.resolve().parent / ca_file
    messages = [
        {"role": "system", "content": "你是业务查询助手。查询订单必须调用 get_order_status，不能猜测状态。得到工具结果后，仅输出包含 order_id、status、source 的 JSON 对象，字段值与工具结果完全一致。"},
        {"role": "user", "content": f"请查询订单 {args.order_id} 的状态。"},
    ]
    with VlmClient(os.getenv("VLM_BASE_URL", cfg["base_url"]), api_key=os.getenv("GPU_API_KEY", os.getenv("VLM_API_KEY", "")),
                   model=cfg["model"], timeout_seconds=cfg["timeout_seconds"],
                   ca_file=ca_file) as client:
        first = client.chat(messages, tools=TOOLS, tool_choice="auto", max_tokens=cfg["max_tokens"], thinking=cfg["thinking"])
        message = first["choices"][0]["message"]
        calls = message.get("tool_calls") or []
        if len(calls) != 1:
            raise ValueError("expected exactly one model-generated tool call; no tool was executed")
        # Validate the entire proposed call before any execution; never eval model output.
        result = execute_readonly_tool(calls[0])
        messages.append({"role": "assistant", "content": message.get("content"), "tool_calls": calls})
        messages.append({"role": "tool", "tool_call_id": calls[0]["id"], "content": json.dumps(result, ensure_ascii=False)})
        final = client.chat(messages, tools=TOOLS, tool_choice="none", max_tokens=cfg["max_tokens"], thinking=cfg["thinking"])
    print(json.dumps({"demo_only": True, "tool_calls": calls, "tool_results": [result], "final_response": final}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError, KeyError) as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1)
