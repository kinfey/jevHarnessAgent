from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


DEFAULT_ORDER = "我要一份板燒雞腿堡套餐，中杯可樂，到店取餐。先試算，不要真正下單。"


@dataclass(frozen=True)
class OrderPlan:
    fulfillment: str
    meal: str
    size: str
    drink: str
    quantity: int
    action: str
    confidence: float
    needs_review: bool

    def as_prompt(self) -> str:
        return (
            f"fulfillment={self.fulfillment}; meal={self.meal}; size={self.size}; "
            f"drink={self.drink}; quantity={self.quantity}; action={self.action}; "
            f"decision_confidence={self.confidence:.3f}"
        )


@dataclass
class RunMetrics:
    engine: str
    elapsed_seconds: float
    model_stages: int
    tool_events: int
    steps: list[str] = field(default_factory=list)
    jev_decisions: dict[str, Any] | None = None
    agent_context: dict[str, Any] = field(default_factory=dict)
    token_usage: dict[str, Any] = field(default_factory=dict)
    event_types: dict[str, int] = field(default_factory=dict)
    response: str = ""
