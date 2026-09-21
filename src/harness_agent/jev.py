from __future__ import annotations

import asyncio
import os
from typing import Any

from typesafe_sdk import AsyncTypeSafeClient, Choice

from .config import Settings
from .models import OrderPlan


QUESTIONS = {
    "fulfillment": Choice(
        instructions="使用者要求哪一種取餐方式？若沒有明說，選 unknown。",
        criteria={
            "pickup": "到店取餐、店取或自取",
            "delivery": "外送或送到地址",
            "dine_in": "在餐廳內用",
            "unknown": "未說明取餐方式",
        },
    ),
    "meal": Choice(
        instructions="使用者要的主套餐是哪一個？",
        criteria={
            "grilled_chicken_combo": "板燒雞腿堡套餐",
            "other": "任何其他餐點或無法判定",
        },
    ),
    "size": Choice(
        instructions="使用者指定的套餐尺寸是什麼？若未指定，選 regular。",
        criteria={
            "regular": "中份、標準份或未指定尺寸",
            "large": "大份或升級大套餐",
        },
    ),
    "drink": Choice(
        instructions="使用者指定的飲料是什麼？若未指定，選 not_stated。",
        criteria={
            "coke": "可口可樂或可樂",
            "coke_zero": "零度可樂或無糖可樂",
            "sprite": "雪碧",
            "coffee": "咖啡",
            "not_stated": "未指定飲料",
        },
    ),
    "quantity": Choice(
        instructions="使用者要幾份套餐？",
        criteria={"1": "一份或未指定數量", "2": "兩份", "3": "三份", "other": "其他數量"},
    ),
    "action": Choice(
        instructions="使用者現在允許系統執行到哪一步？",
        criteria={
            "quote_only": "只查詢、選餐、套用優惠或試算，不建立訂單",
            "create_order": "明確要求建立或提交訂單",
        },
    ),
}


async def compile_order_with_trace(
    request: str, settings: Settings
) -> tuple[OrderPlan, dict[str, Any]]:
    settings.require_typesafe()
    os.environ["TYPESAFE_API_KEY"] = settings.typesafe_api_key

    async with AsyncTypeSafeClient(model=settings.typesafe_model) as client:
        result = await client.system_one(request, QUESTIONS)

    answers = result.choices
    confidence = min(answer.confidence for answer in answers.values())
    quantity_value = answers["quantity"].choice
    quantity = int(quantity_value) if quantity_value in {"1", "2", "3"} else 1
    missing_required = (
        answers["fulfillment"].choice == "unknown"
        or answers["meal"].choice == "other"
        or answers["drink"].choice == "not_stated"
    )
    plan = OrderPlan(
        fulfillment=answers["fulfillment"].choice,
        meal=answers["meal"].choice,
        size=answers["size"].choice,
        drink=answers["drink"].choice,
        quantity=quantity,
        action=answers["action"].choice,
        confidence=confidence,
        needs_review=missing_required or confidence < settings.confidence_threshold,
    )
    decisions = {
        name: {
            "choice": answer.choice,
            "confidence": answer.confidence,
            "probabilities": dict(answer.probabilities),
        }
        for name, answer in answers.items()
    }
    return plan, {
        "model": settings.typesafe_model,
        "questions_evaluated_in_parallel": list(QUESTIONS),
        "answers": decisions,
        "gate": {
            "minimum_confidence": confidence,
            "threshold": settings.confidence_threshold,
            "missing_required_field": missing_required,
            "needs_review": plan.needs_review,
        },
        "typed_plan": {
            "fulfillment": plan.fulfillment,
            "meal": plan.meal,
            "size": plan.size,
            "drink": plan.drink,
            "quantity": plan.quantity,
            "action": plan.action,
        },
        "usage": {
            "input_tokens": result.usage.input_tokens,
            "output_tokens": result.usage.output_tokens,
        },
    }


async def compile_order(request: str, settings: Settings) -> OrderPlan:
    plan, _ = await compile_order_with_trace(request, settings)
    return plan


def compile_order_sync(request: str, settings: Settings) -> OrderPlan:
    return asyncio.run(compile_order(request, settings))
