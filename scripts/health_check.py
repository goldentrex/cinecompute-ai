"""Pre-demo preflight: verifies ClickHouse, the seeded data, and the Gemini API.

Reads everything from .env / environment - no credentials in this file.

    python scripts/health_check.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.config import settings

OK, FAIL = "  [OK]  ", "  [FAIL]"


def check_clickhouse():
    print(f"ClickHouse -> {settings.clickhouse_host}:{settings.clickhouse_port} "
          f"(secure={settings.clickhouse_secure})")
    try:
        from app.database.clickhouse_client import get_client
        client = get_client(readonly=True)
        print(f"{OK} connected, server {client.server_version}")
    except Exception as e:
        print(f"{FAIL} {type(e).__name__}: {str(e)[:200]}")
        if "SSLZeroReturnError" in str(e) or "TLS/SSL connection has been closed" in str(e):
            print("         The server dropped the TLS handshake. On ClickHouse Cloud this")
            print("         almost always means this machine's public IP is not in the")
            print("         service's IP access list, or the service is stopped.")
        return False

    try:
        db = settings.clickhouse_database
        events = client.query(f"SELECT count() FROM {db}.vfx_render_events").result_rows[0][0]
        budgets = client.query(f"SELECT count() FROM {db}.production_budgets").result_rows[0][0]
        print(f"{OK if events else FAIL} {db}.vfx_render_events: {events:,} rows")
        print(f"{OK if budgets else FAIL} {db}.production_budgets: {budgets:,} rows")
        if not events:
            print("         Run: python scripts/seed_vfx_data.py")
        return bool(events and budgets)
    except Exception as e:
        print(f"{FAIL} tables missing: {str(e)[:160]}")
        print("         Run: python scripts/seed_vfx_data.py")
        return False


def check_mcp_tools():
    """Exercise the official ClickHouse MCP server the same way the agent does."""
    print("\nClickHouse MCP server (mcp-clickhouse)")
    import json
    from app.agent.mcp_client import ClickHouseMCP, run_async, server_command

    print(f"         binary: {server_command()}")

    async def probe():
        async with ClickHouseMCP() as mcp:
            names = [t.name for t in mcp.tools]
            listed, _, err_l = await mcp.call("list_tables",
                                              {"database": settings.clickhouse_database})
            rows, ms, err_q = await mcp.call("run_query", {
                "query": f"SELECT status, count() AS c FROM {settings.clickhouse_database}"
                         ".vfx_render_events GROUP BY status ORDER BY c DESC"})
            blocked, _, err_b = await mcp.call("run_query", {
                "query": f"DROP TABLE {settings.clickhouse_database}.vfx_render_events"})
            return names, (listed, err_l), (rows, ms, err_q), (blocked, err_b)

    try:
        names, (listed, err_l), (rows, ms, err_q), (blocked, err_b) = run_async(probe())
    except Exception as e:
        print(f"{FAIL} could not start the MCP server: {type(e).__name__}: {str(e)[:180]}")
        return False

    print(f"{OK} session initialised, tools: {names}")
    if err_l:
        print(f"{FAIL} list_tables: {listed[:160]}")
        return False
    print(f"{OK} list_tables answered")

    if err_q:
        print(f"{FAIL} run_query: {rows[:160]}")
        return False
    n = len(json.loads(rows).get("rows", [])) if rows.startswith("{") else 0
    print(f"{OK} run_query -> {n} rows in {ms:.1f} ms")

    if err_b:
        print(f"{OK} writes rejected: {blocked.split('.')[0][:70]}")
    else:
        print(f"{FAIL} a DROP was NOT rejected")
        return False
    return True


def check_gemini():
    print(f"\nGemini -> {settings.gemini_model} (with failover)")
    if not settings.gemini_api_key:
        print(f"{FAIL} GEMINI_API_KEY is empty")
        return False

    from google import genai
    from app.agent.gemini_client import FALLBACK_MODELS
    client = genai.Client(api_key=settings.gemini_api_key)

    candidates = [settings.gemini_model] + [m for m in FALLBACK_MODELS if m != settings.gemini_model]
    exhausted = []
    for model in candidates:
        try:
            r = client.models.generate_content(model=model, contents="Reply with OK")
            print(f"{OK} {model} responded: {(r.text or '').strip()[:20]}")
            if exhausted:
                print(f"         Out of quota / unavailable: {', '.join(exhausted)}")
                print("         The demo will still run via failover, but enable billing")
                print("         on the API key to avoid running out mid-presentation.")
            return True
        except Exception as e:
            msg = str(e)
            if any(t in msg for t in ("RESOURCE_EXHAUSTED", "429", "NOT_FOUND", "404",
                                      "UNAVAILABLE", "503")):
                exhausted.append(model)
                continue
            print(f"{FAIL} {model}: {type(e).__name__}: {msg[:180]}")
            return False

    print(f"{FAIL} every candidate model is out of quota or unavailable: {', '.join(exhausted)}")
    print("         Enable billing on the Gemini API key, or wait for the daily quota reset.")
    return False


if __name__ == "__main__":
    results = [check_clickhouse(), check_mcp_tools(), check_gemini()]
    print("\n" + ("ALL CHECKS PASSED - ready to demo." if all(results)
                  else "SOME CHECKS FAILED - see above."))
    sys.exit(0 if all(results) else 1)
