"""Turn the diagnosis into things a pipeline can act on.

Two deterministic passes, both pure SQL:

- `audit()` sweeps every project/sequence/software slice and ranks the incidents
  by wasted spend. Nobody asks it a question; it reports what it finds.
- `policy()` emits the scheduler rules those incidents imply - VRAM routing,
  retry caps, node exclusions - as a file a render manager can consume.

Neither passes through a model, so neither can invent a number. The agent
explains the findings; this decides nothing on its own authority.
"""
import json
from datetime import datetime, timezone

from app.config import settings
from app.database.clickhouse_client import get_client

DB = settings.clickhouse_database
GPU_VRAM_GB = {
    "NVIDIA_A100_80GB": 80, "NVIDIA_H100": 80,
    "NVIDIA_L40S": 48, "NVIDIA_RTX4090": 24,
}
# a slice smaller than this is noise, not a systemic fault
MIN_JOBS = 500
MIN_FAILURE_RATE = 15.0


def audit():
    """Rank every slice of the farm by wasted spend. Returns a DataFrame."""
    import pandas as pd

    client = get_client()
    res = client.query(f"""
        SELECT
            project_id, sequence_id, software, gpu_model,
            count()                                                          AS jobs,
            countIf(status != 'SUCCESS')                                     AS failed,
            round(100.0 * countIf(status != 'SUCCESS') / nullIf(count(), 0), 1) AS failure_rate,
            round(sumIf(cost_usd, status != 'SUCCESS'), 2)                   AS wasted_usd,
            argMax(status, cnt_by_status)                                    AS dominant_failure,
            round(avgIf(vram_peak_gb, status = 'OOM_KILLED'), 1)             AS oom_vram
        FROM (
            SELECT *, count() OVER (PARTITION BY project_id, sequence_id, software,
                                    gpu_model, status) AS cnt_by_status
            FROM {DB}.vfx_render_events
            WHERE status != 'SUCCESS'
        )
        GROUP BY project_id, sequence_id, software, gpu_model
        HAVING failed > 50
        ORDER BY wasted_usd DESC
        LIMIT 12
    """)
    df = pd.DataFrame(res.result_rows, columns=res.column_names)

    # failure_rate above is computed on failures only; recompute on all jobs
    totals = client.query(f"""
        SELECT project_id, sequence_id, software, gpu_model,
               count() AS all_jobs, countIf(status != 'SUCCESS') AS all_failed
        FROM {DB}.vfx_render_events
        GROUP BY project_id, sequence_id, software, gpu_model
    """)
    t = pd.DataFrame(totals.result_rows, columns=totals.column_names)
    df = df.drop(columns=["jobs", "failed", "failure_rate"]).merge(
        t, on=["project_id", "sequence_id", "software", "gpu_model"], how="left")
    df["failure_rate"] = (100.0 * df["all_failed"] / df["all_jobs"]).round(1)
    df["severity"] = df.apply(
        lambda r: "critical" if r["failure_rate"] >= 40 else
                  "high" if r["failure_rate"] >= MIN_FAILURE_RATE else "watch",
        axis=1,
    )
    return df[df["all_jobs"] >= MIN_JOBS].reset_index(drop=True)


def policy(incidents):
    """Scheduler rules implied by the incidents, with the evidence for each."""
    rules = []

    for _, r in incidents.iterrows():
        if r["severity"] == "watch":
            continue

        if r["dominant_failure"] == "OOM_KILLED":
            ceiling = GPU_VRAM_GB.get(r["gpu_model"], 0)
            rules.append({
                "rule": "require_vram",
                "match": {"sequence": r["sequence_id"], "software": r["software"]},
                "min_vram_gb": 80 if ceiling >= 80 else ceiling * 2,
                "reason": (f"{r['all_failed']:,} of {r['all_jobs']:,} jobs killed out of "
                           f"memory on {r['gpu_model']} ({ceiling} GB), peaking at "
                           f"{r['oom_vram']} GB"),
                "recovers_usd": float(r["wasted_usd"]),
            })
        elif r["dominant_failure"] == "DRIVER_CRASH":
            rules.append({
                "rule": "exclude_gpu",
                "match": {"sequence": r["sequence_id"], "software": r["software"]},
                "exclude": r["gpu_model"],
                "reason": (f"{r['all_failed']:,} of {r['all_jobs']:,} jobs "
                           f"({r['failure_rate']}%) crashed the driver on "
                           f"{r['gpu_model']}"),
                "recovers_usd": float(r["wasted_usd"]),
            })
        elif r["dominant_failure"] == "TIMEOUT":
            rules.append({
                "rule": "cap_retries",
                "match": {"sequence": r["sequence_id"], "software": r["software"]},
                "max_retries": 1,
                "reason": f"{r['all_failed']:,} jobs timed out and were retried",
                "recovers_usd": float(r["wasted_usd"]),
            })

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "generated_by": "CineCompute AI",
        "source": f"{DB}.vfx_render_events",
        "note": ("Derived from the telemetry by SQL, not by a language model. "
                 "Every rule carries the counts that justify it."),
        "recoverable_usd": round(sum(r["recovers_usd"] for r in rules), 2),
        "rules": rules,
    }


def policy_json(incidents):
    return json.dumps(policy(incidents), indent=2)
