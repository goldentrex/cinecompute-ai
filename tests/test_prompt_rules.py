"""The system prompt must keep the rules that past mistakes made necessary."""
from app.agent.prompts import SYSTEM_INSTRUCTION as P


def test_distinguishes_total_spend_from_wasted_spend():
    # the agent once reported $101,416 of total Karma spend as waste ($31,680)
    assert "sumIf(cost_usd, status != 'SUCCESS')" in P
    assert "Never present a total as" in P


def test_forbids_uncomputed_rates():
    # it once claimed a 100% crash rate that was actually 61.2%
    assert "NEVER state a rate" in P


def test_forbids_any_for_attribution():
    # any() once attributed Houdini OOM kills to Maya Arnold
    assert "any()" in P and "arbitrary row" in P


def test_forbids_latex():
    assert "Never emit LaTeX" in P


def test_describes_the_real_mcp_tools():
    for tool in ("list_databases()", "list_tables(database)", "run_query(query)"):
        assert tool in P
