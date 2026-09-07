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
