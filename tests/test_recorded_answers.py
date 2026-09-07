"""Every figure in the recorded demo answers must exist in the database.

Needs ClickHouse credentials; skipped automatically when they are absent, so the
fast tests still run anywhere.
"""
import re

import pytest

from app.agent import cache
from app.config import settings

pytestmark = pytest.mark.skipif(
    not settings.clickhouse_password,
    reason="no ClickHouse credentials in the environment",
)

# figures established by independent SQL during development
GROUND_TRUTH = {
    "120461.22": "SEQ_010 spend", "74685.96": "SEQ_010 budget",
    "45775.26": "SEQ_010 overrun", "20968.97": "SEQ_010 wasted",
    "152915.24": "SEQ_045 spend", "134565.41": "SEQ_045 budget",
    "83485": "SEQ_010 tasks", "11290": "SEQ_010 failures",
}
# figures the agent produced at some point and that were wrong
KNOWN_FABRICATIONS = {
    "173728": "rows scanned reported as task count",
    "101416.39": "total spend presented as waste",
    "250450": "invented event total",
    "4259": "overstated OOM count",
}


def _numbers(text):
    return {n.replace(",", "") for n in re.findall(r"\d[\d,]*\.?\d*", text)}


def test_there_are_recorded_runs():
    assert cache.list_cached(), "no recorded runs: the hosted demo has nothing to replay"


def test_no_recorded_answer_contains_a_known_fabrication():
    for question, _, _ in cache.list_cached():
        nums = _numbers(cache.load(question)["answer"])
        for bad, why in KNOWN_FABRICATIONS.items():
            assert bad not in nums, f"{why} reappeared in: {question[:60]}"


def test_recorded_figures_match_the_database():
    """Any ground-truth number quoted must still be true in ClickHouse."""
    from app.database.clickhouse_client import get_client

    client = get_client()
    db = settings.clickhouse_database
    row = client.query(
        f"SELECT round(sum(cost_usd), 2), count(), countIf(status != 'SUCCESS') "
        f"FROM {db}.vfx_render_events WHERE sequence_id = 'SEQ_010_SPACE_BATTLE'"
    ).result_rows[0]
    live = {str(row[0]), str(row[1]), str(row[2])}

    quoted = set()
    for question, _, _ in cache.list_cached():
        quoted |= _numbers(cache.load(question)["answer"]) & set(GROUND_TRUTH)

    assert quoted, "recorded answers quote none of the known figures"
    for value in ("120461.22", "83485", "11290"):
        if value in quoted:
            assert value in live, f"{GROUND_TRUTH[value]} no longer matches the data"


def test_recorded_answers_use_the_three_sections():
    for question, _, _ in cache.list_cached():
        answer = cache.load(question)["answer"]
        assert answer.startswith("### 1."), f"format drifted on: {question[:60]}"
