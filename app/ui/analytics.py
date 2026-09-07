"""Dashboard aggregations. Every figure on screen is computed by ClickHouse."""
import time

import pandas as pd

from app.config import settings
from app.database.clickhouse_client import get_client

DB = settings.clickhouse_database


class QueryTimer:
    """Separates ClickHouse execution time from network round-trip.

    A hosted app can sit an ocean away from the database, so wall-clock timing
    mostly measures the link, not the engine. ClickHouse reports its own
    `elapsed_ns` and `read_rows` per query - that is the honest number to show.
    """

    def __init__(self):
        self.total_ms = 0.0        # server-side execution
        self.roundtrip_ms = 0.0    # including network
        self.rows_scanned = 0
        self.count = 0

    def run(self, client, sql):
        start = time.time()
        res = client.query(sql)
        self.roundtrip_ms += (time.time() - start) * 1000
        summary = getattr(res, "summary", None) or {}
        try:
            self.total_ms += int(summary.get("elapsed_ns", 0)) / 1e6
            self.rows_scanned += int(summary.get("read_rows", 0))
        except (TypeError, ValueError):
            pass
        self.count += 1
        return res

    def df(self, client, sql):
        res = self.run(client, sql)
        return pd.DataFrame(res.result_rows, columns=res.column_names)


def load_dashboard():
    """Return (kpis, frames, timing, error)."""
    timer = QueryTimer()
    try:
        client = get_client(readonly=True)

        kpi = timer.run(client, f"""
            SELECT
                sum(cost_usd)                                             AS total_spend,
                100.0 * countIf(status != 'SUCCESS') / nullIf(count(), 0) AS failure_rate,
                sumIf(cost_usd, status != 'SUCCESS')                      AS wasted,
                count()                                                   AS events,
                sumIf(compute_duration_sec, status != 'SUCCESS') / 3600.0 AS wasted_gpu_hours
            FROM {DB}.vfx_render_events
        """).result_rows[0]

        budget = timer.df(client, f"""
            SELECT
                b.sequence_id                                                        AS sequence_id,
                round(sum(e.cost_usd), 2)                                            AS spend_usd,
                round(b.allocated_budget_usd, 2)                                     AS budget_usd,
                round(100.0 * sum(e.cost_usd) / nullIf(b.allocated_budget_usd, 0) - 100, 1) AS overrun_pct
            FROM {DB}.vfx_render_events e
            INNER JOIN {DB}.production_budgets b ON e.sequence_id = b.sequence_id
            GROUP BY b.sequence_id, b.allocated_budget_usd
            ORDER BY overrun_pct DESC
        """)

        waste = timer.df(client, f"""
            SELECT
                software,
                status,
                round(sum(cost_usd), 2) AS wasted_usd
            FROM {DB}.vfx_render_events
            WHERE status != 'SUCCESS'
            GROUP BY software, status
            ORDER BY wasted_usd DESC
        """)

        hotspots = timer.df(client, f"""
            SELECT
                concat(project_id, ' · ', sequence_id, ' · ', software) AS slice,
                round(100.0 * countIf(status != 'SUCCESS') / nullIf(count(), 0), 1) AS failure_rate,
                round(sumIf(cost_usd, status != 'SUCCESS'), 2)                      AS wasted_usd,
                count()                                                             AS jobs
            FROM {DB}.vfx_render_events
            GROUP BY slice
            HAVING jobs > 500
            ORDER BY failure_rate DESC
            LIMIT 8
        """)

        # The actionable number: waste traceable to the two systemic faults the
        # agent is meant to find, as opposed to irreducible background failures.
        recoverable = timer.run(client, f"""
            SELECT
                round(sumIf(cost_usd,
                    project_id = 'DUNE_CH3' AND sequence_id = 'SEQ_010_SPACE_BATTLE'
                    AND software = 'Houdini_Karma' AND status = 'OOM_KILLED'), 2) AS oom_waste,
                round(sumIf(cost_usd,
                    sequence_id = 'SEQ_045_UNDERWATER' AND gpu_model = 'NVIDIA_L40S'
                    AND status = 'DRIVER_CRASH'), 2)                                AS crash_waste
            FROM {DB}.vfx_render_events
        """).result_rows[0]

        burn = timer.df(client, f"""
            SELECT
                toDate(event_time)                            AS day,
                round(sumIf(cost_usd, status = 'SUCCESS'), 2)  AS productive_usd,
                round(sumIf(cost_usd, status != 'SUCCESS'), 2) AS wasted_usd
            FROM {DB}.vfx_render_events
            GROUP BY day
            ORDER BY day
        """)

        kpis = {
            "total_spend": kpi[0] or 0,
            "failure_rate": kpi[1] or 0,
            "wasted": kpi[2] or 0,
            "events": kpi[3] or 0,
            "wasted_gpu_hours": kpi[4] or 0,
            "top_sequence": budget.iloc[0]["sequence_id"] if len(budget) else "N/A",
            "top_overrun": budget.iloc[0]["overrun_pct"] if len(budget) else 0,
            "over_budget_count": int((budget["overrun_pct"] > 0).sum()) if len(budget) else 0,
            "oom_waste": recoverable[0] or 0,
            "crash_waste": recoverable[1] or 0,
            "recoverable": (recoverable[0] or 0) + (recoverable[1] or 0),
        }
        frames = {"budget": budget, "waste": waste, "hotspots": hotspots, "burn": burn}
        timing = {
            "total_ms": round(timer.total_ms, 1),
            "roundtrip_ms": round(timer.roundtrip_ms, 1),
            "rows_scanned": timer.rows_scanned,
            "queries": timer.count,
        }
        return kpis, frames, timing, None

    except Exception as e:
        return None, None, {"total_ms": 0, "roundtrip_ms": 0,
                            "rows_scanned": 0, "queries": 0}, str(e)
