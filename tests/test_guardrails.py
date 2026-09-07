"""Safety properties of the MCP path. No model calls, no API cost."""
import pytest

from app.agent.mcp_client import READ_PREFIXES, ClickHouseMCP, run_async


def test_read_prefixes_cover_the_reads_we_rely_on():
    for verb in ("select", "with", "show", "describe", "explain"):
        assert verb in READ_PREFIXES


@pytest.mark.parametrize("statement", [
    "DROP TABLE cinecompute.vfx_render_events",
    "INSERT INTO cinecompute.vfx_render_events VALUES (1)",
    "ALTER TABLE cinecompute.vfx_render_events DELETE WHERE 1",
    "TRUNCATE TABLE cinecompute.vfx_render_events",
])
def test_writes_are_refused_before_reaching_the_server(statement):
    """The client-side allowlist rejects writes without a round-trip."""
    async def probe():
        mcp = ClickHouseMCP.__new__(ClickHouseMCP)   # no server needed
        return await mcp.call("run_query", {"query": statement})

    payload, elapsed, failed = run_async(probe())
    assert failed, f"{statement!r} was not refused"
    assert "only read statements" in payload
    assert elapsed == 0.0, "refusal must not cost a round-trip"


def test_multiple_statements_are_refused():
    async def probe():
        mcp = ClickHouseMCP.__new__(ClickHouseMCP)
        return await mcp.call("run_query", {"query": "SELECT 1; SELECT 2"})

    payload, _, failed = run_async(probe())
    assert failed and "multiple statements" in payload.lower()


def test_engine_metrics_never_reach_the_model():
    """rows_scanned was once reported as a business figure; keep it UI-only."""
    from app.agent.gemini_client import UI_ONLY_KEYS
    assert {"latency_ms", "rows_scanned", "roundtrip_ms"} <= UI_ONLY_KEYS


def test_remediation_policy_never_invents_a_figure():
    """Every rule must carry counts that come from the sweep, not from a model."""
    import pytest

    from app.config import settings
    if not settings.clickhouse_password:
        pytest.skip("no ClickHouse credentials")

    from app.remediation import audit, policy

    incidents = audit()
    doc = policy(incidents)

    assert doc["rules"], "the farm has known systemic faults; none were turned into rules"
    for rule in doc["rules"]:
        assert rule["reason"], "a rule without evidence is an assertion"
        assert rule["recovers_usd"] > 0
        assert rule["match"]["sequence"] in set(incidents["sequence_id"])
    # the headline must be the sum of the parts, not a separate claim
    assert abs(doc["recoverable_usd"]
               - round(sum(r["recovers_usd"] for r in doc["rules"]), 2)) < 0.01
