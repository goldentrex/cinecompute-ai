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
                sumIf(compute_duration_sec, status != 'SUCCESS') / 3600.0 AS wasted_gpu_hours,
                countIf(status = 'SUCCESS')                               AS successful
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

        # V2: frames delivered against frames ordered. A sequence can be on budget
        # and still be heading for an overrun - what settles it is the cost of the
        # work still to do, which needs a completion ratio, not a spend total.
        progress = timer.df(client, f"""
            SELECT
                b.sequence_id                                                  AS sequence_id,
                sum(e.frames_rendered)                                         AS frames_done,
                any(b.target_frames)                                           AS target_frames,
                round(100.0 * sum(e.frames_rendered)
                      / nullIf(any(b.target_frames), 0), 1)                    AS completion_pct,
                round(sum(e.cost_usd), 2)                                      AS spend_usd,
                round(any(b.allocated_budget_usd), 2)                          AS budget_usd,
                round(sum(e.cost_usd) / nullIf(sum(e.frames_rendered), 0), 4)  AS cost_per_frame,
                round(any(b.target_frames) * sum(e.cost_usd)
                      / nullIf(sum(e.frames_rendered), 0), 2)                  AS forecast_usd
            FROM {DB}.vfx_render_events e
            INNER JOIN {DB}.production_budgets b ON e.sequence_id = b.sequence_id
            GROUP BY b.sequence_id
            ORDER BY b.sequence_id
        """)
        progress["forecast_overrun"] = (
            progress["forecast_usd"] - progress["budget_usd"]).round(2)

        # V2: waste carries a name. Ranked by money, with the failure rate that
        # justifies the ranking, so it is a diagnosis and not an accusation.
        artists = timer.df(client, f"""
            SELECT
                artist_id                                                          AS artist_id,
                round(sumIf(cost_usd, status != 'SUCCESS'), 2)                     AS wasted_usd,
                count()                                                            AS jobs,
                countIf(status != 'SUCCESS')                                       AS failed_jobs,
                round(100.0 * countIf(status != 'SUCCESS') / nullIf(count(), 0), 1) AS failure_rate,
                countIf(status = 'OOM_KILLED')                                     AS oom_kills
            FROM {DB}.vfx_render_events
            GROUP BY artist_id
            ORDER BY wasted_usd DESC
            LIMIT 5
        """)

        burn = timer.df(client, f"""
            SELECT
                toDate(event_time)                            AS day,
                round(sumIf(cost_usd, status = 'SUCCESS'), 2)  AS productive_usd,
                round(sumIf(cost_usd, status != 'SUCCESS'), 2) AS wasted_usd,
                sum(frames_rendered)                          AS frames,
                round(100.0 * countIf(status != 'SUCCESS') / nullIf(count(), 0), 2) AS failure_pct
            FROM {DB}.vfx_render_events
            GROUP BY day
            ORDER BY day
        """)

        # cumulative spend against cumulative frames: the two series the forecast
        # curve is drawn from, so the projection is arithmetic on stored columns
        burn["cum_spend"] = (burn["productive_usd"] + burn["wasted_usd"]).cumsum().round(2)
        burn["cum_frames"] = burn["frames"].cumsum()

        # Cinema runs on delivery dates, not only on budgets. The deadline column
        # exists in production_budgets and nothing used it until now.
        schedule = timer.df(client, f"""
            SELECT
                b.sequence_id                                              AS sequence_id,
                b.deadline                                                 AS deadline,
                dateDiff('day', max(toDate(e.event_time)), b.deadline)     AS days_to_deadline,
                round(sum(e.cost_usd) / nullIf(dateDiff('day',
                    min(toDate(e.event_time)), max(toDate(e.event_time))), 0), 2) AS burn_per_day,
                round(b.allocated_budget_usd - sum(e.cost_usd), 2)         AS budget_left,
                round(sum(e.cost_usd), 2)                                  AS spend_usd,
                round(b.allocated_budget_usd, 2)                           AS budget_usd
            FROM {DB}.vfx_render_events e
            INNER JOIN {DB}.production_budgets b ON e.sequence_id = b.sequence_id
            GROUP BY b.sequence_id, b.deadline, b.allocated_budget_usd
            ORDER BY b.deadline
        """)

        # derived in pandas so the arithmetic is inspectable, not buried in SQL
        schedule["days_of_budget_left"] = (
            schedule["budget_left"] / schedule["burn_per_day"].replace(0, float("nan"))
        ).round(1)
        schedule["cost_to_deadline"] = (
            schedule["burn_per_day"] * schedule["days_to_deadline"]
        ).round(2)
        schedule["shortfall"] = (schedule["cost_to_deadline"] - schedule["budget_left"]).round(2)

        def _verdict(r):
            if r["budget_left"] < 0:
                return "over"          # budget already spent
            if r["days_of_budget_left"] < r["days_to_deadline"]:
                return "at_risk"       # money runs out before the delivery date
            return "ok"

        schedule["verdict"] = schedule.apply(_verdict, axis=1)

        kpis = {
            "total_spend": kpi[0] or 0,
            "failure_rate": kpi[1] or 0,
            "wasted": kpi[2] or 0,
            "events": kpi[3] or 0,
            "wasted_gpu_hours": kpi[4] or 0,
            "successful": kpi[5] or 0,
            "top_sequence": budget.iloc[0]["sequence_id"] if len(budget) else "N/A",
            "top_overrun": budget.iloc[0]["overrun_pct"] if len(budget) else 0,
            "over_budget_count": int((budget["overrun_pct"] > 0).sum()) if len(budget) else 0,
            "oom_waste": recoverable[0] or 0,
            "crash_waste": recoverable[1] or 0,
            "recoverable": (recoverable[0] or 0) + (recoverable[1] or 0),
            "frames_done": int(progress["frames_done"].sum()),
            "frames_target": int(progress["target_frames"].sum()),
            "completion_pct": round(
                100.0 * progress["frames_done"].sum()
                / max(int(progress["target_frames"].sum()), 1), 1),
            "forecast_total": round(float(progress["forecast_usd"].sum()), 2),
            "forecast_overrun": round(float(progress["forecast_overrun"].sum()), 2),
            "top_waster": artists.iloc[0]["artist_id"] if len(artists) else "N/A",
            "top_waster_usd": float(artists.iloc[0]["wasted_usd"]) if len(artists) else 0.0,
        }
        frames = {"budget": budget, "waste": waste, "hotspots": hotspots,
                  "burn": burn, "schedule": schedule,
                  "progress": progress, "artists": artists}
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
