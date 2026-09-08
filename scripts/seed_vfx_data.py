import sys
import os
import random
from datetime import date, datetime, timedelta
import clickhouse_connect

# Add parent directory to path to import app modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.config import settings

DB = settings.clickhouse_database
BATCH_SIZE = 25000
TOTAL_ROWS = 250000

EVENT_COLUMNS = [
    "event_time", "project_id", "sequence_id", "shot_id", "software", "gpu_model",
    "vram_peak_gb", "compute_duration_sec", "cost_usd", "status", "error_details",
    "artist_id", "frames_rendered",
]

# Artists and frame counts were added after the published figures were written
# down. They are drawn from their OWN generator, never from the main stream, so
# every pre-existing column keeps the exact value it had: same costs, same
# statuses, same VRAM peaks, same $97,885 of waste. Inserting a single
# random.random() into the main stream would silently move every number in the
# README, the recorded answers and the audit.
AUX_SEED = 1337
ARTISTS = [f"artist_fx_{i:02d}" for i in range(1, 13)]
# Anomaly 3: one artist's scenes account for most of the memory kills on DUNE_CH3.
# Implemented as attribution over the failures the main stream already generated -
# no failure is added, so no cost or count changes.
OOM_HEAVY_ARTIST = "artist_fx_07"
OOM_HEAVY_PROJECT = "DUNE_CH3"
OOM_HEAVY_SHARE = 0.80

# Frames delivered against frames ordered. Chosen so the forecast has something
# to say: SEQ_010 has spent its whole budget for well under two thirds of the
# work, SEQ_080 is nearly done. target_frames is derived from what was actually
# rendered, so the ratio is exact rather than asserted.
COMPLETION_FACTORS = {
    "SEQ_010_SPACE_BATTLE": 0.58,
    "SEQ_045_UNDERWATER": 0.71,
    "SEQ_080_CITY_CHASE": 0.93,
}

SEQUENCES = ["SEQ_010_SPACE_BATTLE", "SEQ_045_UNDERWATER", "SEQ_080_CITY_CHASE"]

# Physical VRAM per card. Peaks are generated inside these limits so the
# telemetry stays physically plausible under a judge's scrutiny.
GPU_VRAM_GB = {
    "NVIDIA_A100_80GB": 80,
    "NVIDIA_H100": 80,
    "NVIDIA_L40S": 48,
    "NVIDIA_RTX4090": 24,
}
BIG_VRAM_GPUS = ["NVIDIA_A100_80GB", "NVIDIA_H100"]
# clickhouse-connect writes Date columns from datetime.date, not from strings.
DEADLINES = {
    "SEQ_010_SPACE_BATTLE": date(2026, 10, 15),
    "SEQ_045_UNDERWATER": date(2026, 11, 1),
    "SEQ_080_CITY_CHASE": date(2026, 12, 1),
}
# Budget = actual spend * factor, so the demo always has one badly overrun
# sequence, one slightly overrun, and one healthy sequence regardless of RNG.
BUDGET_FACTORS = {
    "SEQ_010_SPACE_BATTLE": 0.62,   # ~61% over budget
    "SEQ_045_UNDERWATER": 0.88,     # ~14% over budget
    "SEQ_080_CITY_CHASE": 1.15,     # ~13% under budget
}


def setup_database_and_tables(client):
    print("Setting up database and schemas...")
    client.command(f"CREATE DATABASE IF NOT EXISTS {DB}")

    client.command(f"""
        CREATE TABLE IF NOT EXISTS {DB}.vfx_render_events (
            event_time DateTime,
            project_id LowCardinality(String),
            sequence_id LowCardinality(String),
            shot_id String,
            software LowCardinality(String),
            gpu_model LowCardinality(String),
            vram_peak_gb Float32,
            compute_duration_sec UInt32,
            cost_usd Float32,
            status LowCardinality(String),
            error_details String,
            artist_id LowCardinality(String),
            frames_rendered UInt16
        ) ENGINE = MergeTree()
        ORDER BY (project_id, sequence_id, event_time)
    """)

    client.command(f"""
        CREATE TABLE IF NOT EXISTS {DB}.production_budgets (
            sequence_id String,
            allocated_budget_usd Float64,
            deadline Date,
            target_frames UInt32
        ) ENGINE = MergeTree()
        ORDER BY sequence_id
    """)

    # An existing deployment already has these tables without the V2 columns, and
    # CREATE TABLE IF NOT EXISTS will not add them.
    for table, column in (
        ("vfx_render_events", "artist_id LowCardinality(String)"),
        ("vfx_render_events", "frames_rendered UInt16"),
        ("production_budgets", "target_frames UInt32"),
    ):
        client.command(f"ALTER TABLE {DB}.{table} ADD COLUMN IF NOT EXISTS {column}")


def seed_data(client):
    print("Truncating old data if exists...")
    client.command(f"TRUNCATE TABLE IF EXISTS {DB}.vfx_render_events")
    client.command(f"TRUNCATE TABLE IF EXISTS {DB}.production_budgets")

    print(f"Generating {TOTAL_ROWS:,} render events... (this may take a moment)")

    random.seed(42)  # reproducible demo data
    aux = random.Random(AUX_SEED)  # artists and frames only - see AUX_SEED above

    projects = ["DUNE_CH3", "AVATAR_DEEP", "CYBER_NEO"]
    softwares = ["Houdini_Karma", "Maya_Arnold", "Nuke_Comp", "Blender_Cycles"]
    gpus = list(GPU_VRAM_GB)
    failure_statuses = ["OOM_KILLED", "TIMEOUT", "DRIVER_CRASH"]

    spend_by_sequence = {seq: 0.0 for seq in SEQUENCES}
    frames_by_sequence = {seq: 0 for seq in SEQUENCES}
    start_time = datetime.now() - timedelta(days=30)

    for batch_i in range(TOTAL_ROWS // BATCH_SIZE):
        data = []
        for _ in range(BATCH_SIZE):
            event_time = start_time + timedelta(minutes=random.randint(0, 30 * 24 * 60))
            project = random.choice(projects)
            sequence = random.choice(SEQUENCES)
            shot_id = f"SH_{random.randint(100, 999)}"
            software = random.choice(softwares)
            gpu = random.choice(gpus)

            capacity = GPU_VRAM_GB[gpu]
            error_details = ""
            vram_peak = random.uniform(6.0, capacity * 0.85)
            duration = random.randint(10, 3600)

            # Baseline: 90% of the farm succeeds.
            if random.random() < 0.9:
                status = "SUCCESS"
            else:
                status = random.choice(failure_statuses)
                error_details = f"Random failure: {status}"
                if status == "OOM_KILLED":
                    # An OOM kill means the job actually hit the card's ceiling.
                    vram_peak = random.uniform(capacity * 0.96, capacity)

            # Anomaly 1: DUNE_CH3 / SEQ_010_SPACE_BATTLE on Houdini_Karma blows past 80GB VRAM.
            if project == "DUNE_CH3" and sequence == "SEQ_010_SPACE_BATTLE" and software == "Houdini_Karma":
                if random.random() < 0.48:
                    status = "OOM_KILLED"
                    # Only an 80GB card can even reach a 78GB peak - keep it consistent.
                    gpu = random.choice(BIG_VRAM_GPUS)
                    capacity = GPU_VRAM_GB[gpu]
                    error_details = "FATAL: Out of memory (VRAM > 78 GB). Geometry too dense."
                    vram_peak = random.uniform(78.1, 79.9)
                    duration = random.randint(300, 7200)  # long, expensive failure

            # Anomaly 2: the L40S pool in SEQ_045_UNDERWATER crashes and burns 3.2x the runtime.
            if sequence == "SEQ_045_UNDERWATER" and gpu == "NVIDIA_L40S":
                if random.random() < 0.60:
                    status = "DRIVER_CRASH"
                    error_details = "NVIDIA Driver Crash - Thermal Throttle / Segmentation Fault"
                    duration = int(duration * 3.2)

            cost = (duration / 3600.0) * random.uniform(1.5, 4.0)
            spend_by_sequence[sequence] += cost

            # --- V2 fields, drawn from `aux` so the row above is untouched ---
            if (status == "OOM_KILLED" and project == OOM_HEAVY_PROJECT
                    and aux.random() < OOM_HEAVY_SHARE):
                artist = OOM_HEAVY_ARTIST
            else:
                artist = aux.choice(ARTISTS)
            # A task that failed delivered nothing - that is what makes waste waste.
            frames = aux.randint(1, 6) if status == "SUCCESS" else 0
            frames_by_sequence[sequence] += frames

            data.append([
                event_time, project, sequence, shot_id, software, gpu,
                vram_peak, int(duration), cost, status, error_details,
                artist, frames,
            ])

        client.insert(f"{DB}.vfx_render_events", data, column_names=EVENT_COLUMNS)
        print(f"Inserted batch {batch_i + 1}/{TOTAL_ROWS // BATCH_SIZE}")

    print("Inserting production budgets (calibrated against actual spend)...")
    # target_frames is derived from the frames actually delivered, so "58% complete"
    # is an exact ratio of two stored numbers rather than a claim.
    budgets_data = [
        [seq, round(spend_by_sequence[seq] * BUDGET_FACTORS[seq], 2), DEADLINES[seq],
         int(round(frames_by_sequence[seq] / COMPLETION_FACTORS[seq]))]
        for seq in SEQUENCES
    ]
    for seq, budget, _, target in budgets_data:
        done = frames_by_sequence[seq]
        print(f"  {seq}: spend ${spend_by_sequence[seq]:,.2f} vs budget ${budget:,.2f} · "
              f"{done:,}/{target:,} frames ({100.0 * done / target:.1f}%)")
    client.insert(
        f"{DB}.production_budgets", budgets_data,
        column_names=["sequence_id", "allocated_budget_usd", "deadline", "target_frames"],
    )

    print("Data seeding complete!")


# Every figure published in the README, in SUBMISSION.md and in the recorded
# answers comes from these aggregates. They are asserted after every re-seed:
# if a change to the generator moves the main random stream, the run fails here
# instead of quietly invalidating the whole submission.
INVARIANTS = {
    "events": 250000,
    "total_spend": 387998.4788,
    "wasted": 97884.7044,
    "oom_waste": 10079.1946,
    "crash_waste": 55919.3307,
    "successful": 210578,
    "wasted_gpu_hours": 35507.9806,
}


def check_invariants(client):
    row = client.query(f"""
        SELECT count(), round(sum(cost_usd), 4),
               round(sumIf(cost_usd, status != 'SUCCESS'), 4),
               round(sumIf(cost_usd, project_id = 'DUNE_CH3'
                    AND sequence_id = 'SEQ_010_SPACE_BATTLE'
                    AND software = 'Houdini_Karma' AND status = 'OOM_KILLED'), 4),
               round(sumIf(cost_usd, sequence_id = 'SEQ_045_UNDERWATER'
                    AND gpu_model = 'NVIDIA_L40S' AND status = 'DRIVER_CRASH'), 4),
               countIf(status = 'SUCCESS'),
               round(sumIf(compute_duration_sec, status != 'SUCCESS') / 3600.0, 4)
        FROM {DB}.vfx_render_events
    """).result_rows[0]
    got = dict(zip(INVARIANTS, row))
    ok = True
    print("\nPublished figures (must not move):")
    for key, expected in INVARIANTS.items():
        same = abs(float(got[key]) - float(expected)) < 0.01
        ok = ok and same
        print(f"  {key:<17} {got[key]:>14,.2f}  expected {expected:>14,.2f}  "
              f"[{'OK' if same else 'CHANGED'}]")
    if not ok:
        print("\n  A published figure moved. Adding a draw to the main random "
              "stream shifts every row after it - use the `aux` generator.")
    return ok


def verify(client):
    print("\n--- VERIFICATION ---")
    events = client.query(f"SELECT count() FROM {DB}.vfx_render_events").result_rows[0][0]
    budgets = client.query(f"SELECT count() FROM {DB}.production_budgets").result_rows[0][0]
    print(f"vfx_render_events rows : {events:,}")
    print(f"production_budgets rows: {budgets:,}")

    print("\nStatus breakdown:")
    for status, cnt, cost in client.query(
        f"SELECT status, count() AS c, round(sum(cost_usd), 2) FROM {DB}.vfx_render_events "
        f"GROUP BY status ORDER BY c DESC"
    ).result_rows:
        print(f"  {status:<14} {cnt:>8,}  ${cost:>12,.2f}")

    print("\nVRAM peak vs card capacity (max peak per GPU):")
    for gpu, mx in client.query(
        f"SELECT gpu_model, round(max(vram_peak_gb), 1) FROM {DB}.vfx_render_events GROUP BY gpu_model ORDER BY gpu_model"
    ).result_rows:
        cap = GPU_VRAM_GB.get(gpu, 0)
        flag = "OK" if mx <= cap else "IMPLAUSIBLE"
        print(f"  {gpu:<18} max {mx:>5.1f} GB / {cap} GB  [{flag}]")

    print("\nOOM rate for DUNE_CH3 / SEQ_010_SPACE_BATTLE / Houdini_Karma:")
    rate = client.query(
        f"SELECT round(100.0 * countIf(status = 'OOM_KILLED') / nullIf(count(), 0), 2) "
        f"FROM {DB}.vfx_render_events "
        f"WHERE project_id = 'DUNE_CH3' AND sequence_id = 'SEQ_010_SPACE_BATTLE' "
        f"AND software = 'Houdini_Karma'"
    ).result_rows[0][0]
    print(f"  {rate}%")

    print("\nFrames delivered against frames ordered:")
    for seq, done, target, pct in client.query(f"""
        SELECT b.sequence_id, sum(e.frames_rendered) AS done, any(b.target_frames) AS target,
               round(100.0 * sum(e.frames_rendered) / nullIf(any(b.target_frames), 0), 1)
        FROM {DB}.vfx_render_events e
        INNER JOIN {DB}.production_budgets b ON e.sequence_id = b.sequence_id
        GROUP BY b.sequence_id ORDER BY b.sequence_id
    """).result_rows:
        print(f"  {seq:<22} {done:>8,} / {target:>8,} frames  {pct:>5}%")

    print(f"\nShare of {OOM_HEAVY_PROJECT} memory kills owned by each artist (top 3):")
    for artist, kills, share in client.query(f"""
        SELECT artist_id, count() AS kills,
               round(100.0 * count() / (SELECT count() FROM {DB}.vfx_render_events
                   WHERE project_id = '{OOM_HEAVY_PROJECT}' AND status = 'OOM_KILLED'), 1)
        FROM {DB}.vfx_render_events
        WHERE project_id = '{OOM_HEAVY_PROJECT}' AND status = 'OOM_KILLED'
        GROUP BY artist_id ORDER BY kills DESC LIMIT 3
    """).result_rows:
        print(f"  {artist:<16} {kills:>7,} kills  {share:>5}%")

    invariants_ok = check_invariants(client)

    if events != TOTAL_ROWS:
        print(f"\nWARNING: expected {TOTAL_ROWS:,} events, found {events:,}")
        return False
    return invariants_ok


if __name__ == "__main__":
    try:
        client = clickhouse_connect.get_client(
            host=settings.clickhouse_host,
            port=settings.clickhouse_port,
            username=settings.clickhouse_user,
            password=settings.clickhouse_password,
            secure=settings.clickhouse_secure,
            verify=settings.clickhouse_verify,
            compress=True,
            connect_timeout=settings.clickhouse_connect_timeout,
            send_receive_timeout=settings.clickhouse_query_timeout,
        )
        print(f"Connected to ClickHouse {client.server_version} at {settings.clickhouse_host}")
        setup_database_and_tables(client)
        seed_data(client)
        sys.exit(0 if verify(client) else 1)
    except Exception as e:
        print(f"Error seeding data: {type(e).__name__}: {e}")
        sys.exit(1)
