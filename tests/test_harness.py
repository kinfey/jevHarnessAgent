from harness_agent.config import Settings
from harness_agent.copilot_runner import allowed_tools
from harness_agent.models import OrderPlan
from harness_agent.simulation import render_simulation


def plan(fulfillment: str = "pickup") -> OrderPlan:
    return OrderPlan(
        fulfillment=fulfillment,
        meal="grilled_chicken_combo",
        size="regular",
        drink="coke",
        quantity=1,
        action="quote_only",
        confidence=0.9,
        needs_review=False,
    )


def test_preview_never_exposes_create_order() -> None:
    assert "create-order" not in allowed_tools(None, commit=False)
    assert "create-order" not in allowed_tools(plan(), commit=False)


def test_commit_exposes_create_order() -> None:
    assert "create-order" in allowed_tools(plan(), commit=True)
    assert "*" not in allowed_tools(None, commit=True)


def test_delivery_only_tools_are_narrowed_by_jev() -> None:
    assert "delivery-query-addresses" not in allowed_tools(plan("pickup"), commit=False)
    assert "delivery-query-addresses" in allowed_tools(plan("delivery"), commit=False)


def test_placeholder_tokens_are_rejected() -> None:
    settings = Settings(mcp_token="YOUR_MCP_TOKEN", typesafe_api_key="YOUR_TYPESAFE_API_KEY")
    try:
        settings.require_mcp()
    except ValueError as error:
        assert "YOUR_MCP_TOKEN" in str(error)
    else:
        raise AssertionError("placeholder MCP token should be rejected")


def test_simulation_is_side_effect_free() -> None:
    output = render_simulation()
    assert "create-order is not exposed" in output
    assert "calculate-price" in output


def test_mcp_context_never_contains_token() -> None:
    settings = Settings(mcp_token="secret-token", typesafe_api_key="secret-key")
    from harness_agent.copilot_runner import mcd_server

    server = mcd_server(settings, ["query-meals"])["mcd"]
    assert server["headers"]["Authorization"] == "Bearer secret-token"
    assert "secret-token" not in repr({"mcp_server": server["url"], "tools": server["tools"]})
