from __future__ import annotations

import asyncio
import time
from collections import Counter
from collections.abc import Callable
from pathlib import Path

from copilot import CopilotClient, ToolSet
from copilot.session import MCPHTTPServerConfig, PermissionHandler
from copilot.session_events import AssistantUsageData

from .config import Settings
from .models import OrderPlan, RunMetrics

ProgressHandler = Callable[[dict[str, object]], None]

MESSAGES = {
    "zh-TW": {
        "traditional_context": "建立傳統 Agent 原始上下文",
        "traditional_load": "載入 {count} 個 MCP 工具並啟動 {model}",
        "traditional_loop": "送出原始需求，進入 Agent loop",
        "traditional_complete": "傳統 Harness 執行完成",
        "jev_start": "並行啟動 Jev 決策與精簡 Copilot runtime",
        "jev_decision": "Typed plan 完成，最低 confidence={confidence:.3f}",
        "jev_review": "信心閘門要求人工審核，停止 MCP 執行",
        "jev_gate": "信心閘門通過；工具集合縮減為 {count} 個",
        "jev_execute": "交給 GPT-6-astra 執行 typed plan",
        "jev_complete": "Jev Harness 執行完成",
    },
    "zh-CN": {
        "traditional_context": "构建传统 Agent 原始上下文",
        "traditional_load": "加载 {count} 个 MCP 工具并启动 {model}",
        "traditional_loop": "发送原始需求，进入 Agent loop",
        "traditional_complete": "传统 Harness 执行完成",
        "jev_start": "并行启动 Jev 决策与精简 Copilot runtime",
        "jev_decision": "Typed plan 完成，最低 confidence={confidence:.3f}",
        "jev_review": "置信度闸门要求人工审核，停止 MCP 执行",
        "jev_gate": "置信度闸门通过；工具集合缩减为 {count} 个",
        "jev_execute": "交给 GPT-6-astra 执行 typed plan",
        "jev_complete": "Jev Harness 执行完成",
    },
    "en": {
        "traditional_context": "Build the traditional agent context",
        "traditional_load": "Load {count} MCP tools and start {model}",
        "traditional_loop": "Send the raw request and enter the agent loop",
        "traditional_complete": "Traditional Harness completed",
        "jev_start": "Start Jev decisions and the minimal Copilot runtime concurrently",
        "jev_decision": "Typed plan ready; minimum confidence={confidence:.3f}",
        "jev_review": "Confidence gate requires human review; MCP execution stopped",
        "jev_gate": "Confidence gate passed; tool set reduced to {count}",
        "jev_execute": "Execute the typed plan with GPT-6-astra",
        "jev_complete": "Jev Harness completed",
    },
}

STEPS = {
    "zh-TW": {
        "traditional": [
            "從原始使用者需求建立寬上下文",
            "暴露傳統點餐 MCP 工具集合",
            "由 GPT-6-astra 逐步選擇下一個 MCP 工具",
            "持續執行直到完成試算或需要更多輸入",
            "產生最終摘要",
        ],
        "jev": [
            "並行啟動 Jev 分類與最小 Copilot runtime",
            "在單次 System One 請求中平行評估 6 個問題",
            "將答案編譯成 OrderPlan",
            "由 Python 執行信心、必要欄位及副作用閘門",
            "選擇 typed plan 所需的最小 MCP 工具集合",
            "提供固定五工具執行圖與位置上下文給 GPT-6-astra",
            "執行 MCP 並回傳試算摘要",
        ],
    },
    "zh-CN": {
        "traditional": [
            "从原始用户需求构建宽上下文",
            "暴露传统点餐 MCP 工具集合",
            "由 GPT-6-astra 逐步选择下一个 MCP 工具",
            "持续执行直到完成试算或需要更多输入",
            "生成最终摘要",
        ],
        "jev": [
            "并行启动 Jev 分类与最小 Copilot runtime",
            "在单次 System One 请求中并行评估 6 个问题",
            "将答案编译成 OrderPlan",
            "由 Python 执行置信度、必要字段和副作用闸门",
            "选择 typed plan 所需的最小 MCP 工具集合",
            "向 GPT-6-astra 提供固定五工具执行图与位置上下文",
            "执行 MCP 并返回试算摘要",
        ],
    },
    "en": {
        "traditional": [
            "Build a broad context from the raw user request",
            "Expose the traditional ordering MCP tool set",
            "Let GPT-6-astra choose the next MCP tool sequentially",
            "Continue until the quote is complete or more input is required",
            "Generate the final summary",
        ],
        "jev": [
            "Start Jev classification and the minimal Copilot runtime concurrently",
            "Evaluate six questions in one parallel System One request",
            "Compile the answers into an OrderPlan",
            "Apply confidence, required-field, and side-effect gates in Python",
            "Select the minimum MCP tool set required by the typed plan",
            "Give GPT-6-astra a fixed five-tool graph and location context",
            "Execute MCP calls and return the quote summary",
        ],
    },
}


def _message(language: str, key: str, **values: object) -> str:
    messages = MESSAGES.get(language, MESSAGES["zh-TW"])
    return messages[key].format(**values)


def _response_instruction(language: str) -> str:
    return {
        "zh-TW": "請使用繁體中文回答。",
        "zh-CN": "请使用简体中文回答。",
        "en": "Respond in English.",
    }.get(language, "請使用繁體中文回答。")

READ_ONLY_ORDER_TOOLS = [
    "query-nearby-stores",
    "query-meals",
    "query-meal-detail",
    "query-store-coupons",
    "calculate-price",
]
DELIVERY_TOOLS = ["delivery-query-addresses", "delivery-query-stores"]


def allowed_tools(plan: OrderPlan | None, commit: bool) -> list[str]:
    if plan is None:
        tools = [
            "delivery-query-addresses",
            "delivery-query-stores",
            *READ_ONLY_ORDER_TOOLS,
        ]
        if commit:
            tools.append("create-order")
        return tools

    tools = list(READ_ONLY_ORDER_TOOLS)
    if plan.fulfillment == "delivery":
        tools.extend(DELIVERY_TOOLS)
    if commit:
        tools.append("create-order")
    return tools


def mcd_server(settings: Settings, tools: list[str]) -> dict[str, MCPHTTPServerConfig]:
    return {
        "mcd": MCPHTTPServerConfig(
            type="http",
            url=settings.mcp_url,
            headers={"Authorization": f"Bearer {settings.mcp_token}"},
            tools=tools,
        )
    }


async def run_traditional(
    request: str,
    settings: Settings,
    commit: bool = False,
    on_progress: ProgressHandler | None = None,
    language: str = "zh-TW",
) -> RunMetrics:
    settings.require_mcp()
    _emit(
        on_progress,
        "traditional",
        "phase",
        _message(language, "traditional_context"),
    )
    events: Counter[str] = Counter()
    usage_events: list[dict[str, int | float | str | None]] = []
    prompt = (
        "你是麥當勞點餐 Harness Agent。自行理解需求並透過 mcd MCP 依序查門店、"
        "查餐點、查優惠與試算價格。"
        + (
            "使用者已透過 --commit 明確授權建立訂單；提交前仍須在回覆中列出最終內容。"
            if commit
            else "這是模擬模式：不得建立訂單，只能做到 calculate-price。"
        )
        + f"\n使用者需求：{request}"
        + f"\n{_response_instruction(language)}"
    )
    tools = allowed_tools(None, commit)
    started = time.perf_counter()
    _emit(
        on_progress,
        "traditional",
        "context",
        _message(
            language,
            "traditional_load",
            count=len(tools),
            model=settings.copilot_model,
        ),
    )
    async with CopilotClient() as client:
        async with await client.create_session(
            model=settings.copilot_model,
            on_permission_request=PermissionHandler.approve_all,
            mcp_servers=mcd_server(settings, tools),
        ) as session:
            session.on(
                lambda event: _record_event(
                    event, events, usage_events, "traditional", on_progress
                )
            )
            _emit(
                on_progress,
                "traditional",
                "phase",
                _message(language, "traditional_loop"),
            )
            message = await session.send_and_wait(prompt, timeout=180)
    metrics = _metrics("traditional", started, events, usage_events, message)
    metrics.steps = STEPS.get(language, STEPS["zh-TW"])["traditional"]
    metrics.agent_context = {
        "model": settings.copilot_model,
        "prompt": prompt,
        "mcp_server": settings.mcp_url,
        "mcp_tools": tools,
        "commit_enabled": commit,
        "credentials_redacted": True,
        "runtime_mode": "copilot-cli",
    }
    metrics.token_usage = {"copilot": _summarize_usage(usage_events)}
    _emit(
        on_progress,
        "traditional",
        "complete",
        _message(language, "traditional_complete"),
    )
    return metrics


async def run_jev(
    request: str,
    settings: Settings,
    commit: bool = False,
    on_progress: ProgressHandler | None = None,
    language: str = "zh-TW",
) -> RunMetrics:
    from .jev import compile_order_with_trace

    settings.require_mcp()
    started = time.perf_counter()
    _emit(on_progress, "jev", "phase", _message(language, "jev_start"))
    runtime_home = Path.cwd() / ".copilot-runtime" / "jev"
    runtime_home.mkdir(parents=True, exist_ok=True)
    client = CopilotClient(mode="empty", base_directory=str(runtime_home))
    runtime_task = asyncio.create_task(client.start())
    decision_task = asyncio.create_task(compile_order_with_trace(request, settings))
    try:
        plan, jev_decisions = await decision_task
        await runtime_task
    except BaseException:
        runtime_task.cancel()
        await asyncio.gather(runtime_task, return_exceptions=True)
        await client.stop()
        raise
    _emit(
        on_progress,
        "jev",
        "decision",
        _message(language, "jev_decision", confidence=plan.confidence),
        data=jev_decisions,
    )
    if plan.needs_review:
        _emit(on_progress, "jev", "gate", _message(language, "jev_review"))
        await client.stop()
        return RunMetrics(
            engine="jev",
            elapsed_seconds=time.perf_counter() - started,
            model_stages=1,
            tool_events=0,
            steps=[
                "Evaluate all typed Jev questions in parallel",
                "Apply confidence and required-field gates in Python",
                "Stop before exposing MCP tools because review is required",
            ],
            jev_decisions=jev_decisions,
            response=f"Jev confidence gate stopped execution: {plan.as_prompt()}",
        )
    if commit and plan.action != "create_order":
        await client.stop()
        raise ValueError("--commit conflicts with Jev's detected quote-only intent.")

    tools = allowed_tools(plan, commit)
    _emit(
        on_progress,
        "jev",
        "gate",
        _message(language, "jev_gate", count=len(tools)),
    )
    events: Counter[str] = Counter()
    usage_events: list[dict[str, int | float | str | None]] = []
    prompt = (
        "執行 Jev Typed plan，不要重新分類。原始需求只提供位置。"
        "固定執行圖：1 query-nearby-stores 選最近自取門店；"
        "2 query-meals 精確找主套餐；3 query-meal-detail 只查所選套餐；"
        "4 query-store-coupons；5 calculate-price。能在同一回合呼叫的獨立工具請並行。"
        "完成試算後立即停止，以精簡表格回答。"
        + (" 已授權 create-order。" if commit else " 禁止 create-order。")
        + f"\nTyped plan: {plan.as_prompt()}"
        + f"\nLocation context: {request}"
        + f"\n{_response_instruction(language)}"
    )
    try:
        available_tools = ToolSet()
        for tool in tools:
            available_tools.add_mcp(f"mcd-{tool}")
        async with await client.create_session(
            model=settings.copilot_model,
            on_permission_request=PermissionHandler.approve_all,
            mcp_servers=mcd_server(settings, tools),
            enable_session_store=False,
            enable_skills=False,
            enable_config_discovery=False,
            skip_custom_instructions=True,
            available_tools=available_tools,
            large_output={"enabled": False},
        ) as session:
            session.on(
                lambda event: _record_event(event, events, usage_events, "jev", on_progress)
            )
            _emit(on_progress, "jev", "phase", _message(language, "jev_execute"))
            message = await session.send_and_wait(prompt, timeout=180)
    finally:
        await client.stop()
    metrics = _metrics("jev", started, events, usage_events, message)
    metrics.model_stages += 1
    metrics.steps = STEPS.get(language, STEPS["zh-TW"])["jev"]
    metrics.jev_decisions = jev_decisions
    metrics.agent_context = {
        "model": settings.copilot_model,
        "prompt": prompt,
        "mcp_server": settings.mcp_url,
        "mcp_tools": tools,
        "commit_enabled": commit,
        "credentials_redacted": True,
        "runtime_mode": "empty",
        "session_store": False,
        "skills": False,
        "config_discovery": False,
    }
    metrics.token_usage = {
        "jev": jev_decisions["usage"],
        "copilot": _summarize_usage(usage_events),
        "combined_reported": {
            "input_tokens": (
                (jev_decisions["usage"]["input_tokens"] or 0)
                + sum((item["input_tokens"] or 0) for item in usage_events)
            ),
            "output_tokens": (
                (jev_decisions["usage"]["output_tokens"] or 0)
                + sum((item["output_tokens"] or 0) for item in usage_events)
            ),
        },
    }
    _emit(on_progress, "jev", "complete", _message(language, "jev_complete"))
    return metrics


def _emit(
    handler: ProgressHandler | None,
    engine: str,
    kind: str,
    message: str,
    *,
    data: object | None = None,
) -> None:
    if handler is not None:
        payload: dict[str, object] = {
            "engine": engine,
            "kind": kind,
            "message": message,
            "timestamp": time.time(),
        }
        if data is not None:
            payload["data"] = data
        handler(payload)


def _record_event(
    event: object,
    events: Counter[str],
    usage_events: list[dict[str, int | float | str | None]],
    engine: str,
    on_progress: ProgressHandler | None,
) -> None:
    event_type = str(getattr(event, "type", "unknown"))
    events.update([event_type])
    data = getattr(event, "data", None)
    short_type = event_type.rsplit(".", 1)[-1]
    if short_type in {
        "MODEL_CALL_START",
        "TOOL_EXECUTION_START",
        "TOOL_EXECUTION_COMPLETE",
        "ASSISTANT_MESSAGE",
    }:
        tool_name = (
            getattr(data, "tool_name", None)
            or getattr(data, "name", None)
            or getattr(data, "toolName", None)
        )
        detail = f": {tool_name}" if tool_name else ""
        _emit(on_progress, engine, "event", f"{short_type}{detail}")
    if isinstance(data, AssistantUsageData):
        usage = {
            "model": data.model,
            "input_tokens": data.input_tokens,
            "output_tokens": data.output_tokens,
            "cache_read_tokens": data.cache_read_tokens,
            "cache_write_tokens": data.cache_write_tokens,
            "cost": data.cost,
        }
        usage_events.append(usage)
        _emit(
            on_progress,
            engine,
            "usage",
            f"{data.model}: input={data.input_tokens or 0}, output={data.output_tokens or 0}",
            data=usage,
        )


def _summarize_usage(
    usage_events: list[dict[str, int | float | str | None]],
) -> dict[str, object]:
    return {
        "calls": usage_events,
        "totals": {
            "input_tokens": sum((item["input_tokens"] or 0) for item in usage_events),
            "output_tokens": sum((item["output_tokens"] or 0) for item in usage_events),
            "cache_read_tokens": sum(
                (item["cache_read_tokens"] or 0) for item in usage_events
            ),
            "cache_write_tokens": sum(
                (item["cache_write_tokens"] or 0) for item in usage_events
            ),
            "cost": sum(float(item["cost"] or 0) for item in usage_events),
        },
    }


def _metrics(
    engine: str,
    started: float,
    events: Counter[str],
    usage_events: list[dict[str, int | float | str | None]],
    message: object,
) -> RunMetrics:
    event_types = dict(events)
    tool_events = sum(
        count for name, count in events.items() if name.endswith("TOOL_EXECUTION_START")
    )
    data = getattr(message, "data", None)
    response = getattr(data, "content", "") if data is not None else ""
    return RunMetrics(
        engine=engine,
        elapsed_seconds=time.perf_counter() - started,
        model_stages=1,
        tool_events=tool_events,
        token_usage={"copilot": _summarize_usage(usage_events)},
        event_types=event_types,
        response=response,
    )
