"""Run the verifier over the recorded answers and store the verdicts.

Cheaper and far less fragile than re-recording: the analysis is already written,
so only the checks run. Each recording is processed independently, so a failure
on one leaves the others intact.

    python scripts/verify_recordings.py
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.agent import cache, verifier                       # noqa: E402
from app.agent.gemini_client import CineComputeAgent        # noqa: E402
from app.agent.mcp_client import ClickHouseMCP, run_async   # noqa: E402
from app.config import settings                             # noqa: E402


async def main():
    agent = CineComputeAgent()
    if agent.client is None:
        print(f"no model backend: {agent.setup_error}")
        return 1

    runs = cache.list_cached()
    if not runs:
        print("no recordings to verify")
        return 1

    failures = 0
    for question, _, model in runs:
        record = cache.load(question)
        try:
            async with ClickHouseMCP() as mcp:
                verdicts, summary = await asyncio.wait_for(
                    verifier.verify(
                        record["answer"], mcp,
                        lambda **kw: agent._generate(kw["contents"], kw["config"]),
                        settings.clickhouse_database, question,
                    ),
                    timeout=180,
                )
        except Exception as e:
            print(f"  [SKIP] {question[:44]:<44} {type(e).__name__}")
            failures += 1
            continue

        cache.save(question, record["answer"],
                   [(c["name"], c.get("args", {}), c["result"])
                    for c in record.get("tool_calls", [])],
                   record.get("model", model), verdicts, summary)
        flag = "OK " if summary["contradicted"] == 0 else "DIFF"
        print(f"  [{flag}] {question[:44]:<44} "
              f"{summary['confirmed']}/{summary['checked']} re-derived, "
              f"{summary['contradicted']} mismatched")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(run_async(main()))
