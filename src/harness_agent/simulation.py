from __future__ import annotations

from .models import DEFAULT_ORDER


TRADITIONAL_TRACE = [
    "GPT-6-astra interprets the request",
    "GPT-6-astra discovers the full MCD MCP tool set",
    "query-nearby-stores",
    "query-meals",
    "query-meal-detail",
    "query-store-coupons",
    "calculate-price",
    "GPT-6-astra summarizes the quote",
]

JEV_TRACE = [
    "Jev evaluates 6 typed decisions in one parallel request",
    "Code applies confidence and side-effect gates",
    "Code exposes only the required MCD MCP tools",
    "query-nearby-stores",
    "query-meals",
    "query-meal-detail",
    "query-store-coupons",
    "calculate-price",
    "GPT-6-astra summarizes the typed execution result",
]


def render_simulation(request: str = DEFAULT_ORDER) -> str:
    lines = [
        f"Order: {request}",
        "",
        "Traditional Harness Agent:",
        *[f"  {index}. {step}" for index, step in enumerate(TRADITIONAL_TRACE, 1)],
        "",
        "Jev Harness Agent:",
        *[f"  {index}. {step}" for index, step in enumerate(JEV_TRACE, 1)],
        "",
        "Safety result: both traces stop at calculate-price; create-order is not exposed.",
        "Note: this trace compares execution shape, not measured latency.",
    ]
    return "\n".join(lines)

