import re
import time
import json
from app.database.clickhouse_client import get_client
from app.config import settings

MAX_ROWS = 50

_FORBIDDEN = re.compile(
    r"\b(insert|alter|drop|create|truncate|delete|update|attach|detach|rename|grant|optimize|system)\b",
    re.IGNORECASE,
)
_TRAILING_LIMIT = re.compile(r"\blimit\s+\d+(\s*,\s*\d+)?\s*$", re.IGNORECASE)
_TABLE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def list_tables() -> str:
    """Returns a list of available tables in the cinecompute database."""
    try:
        client = get_client(readonly=True)
        result = client.query(f"SHOW TABLES FROM {settings.clickhouse_database}")
        tables = [row[0] for row in result.result_rows]
        return json.dumps({"tables": tables})
    except Exception as e:
        return json.dumps({"error": str(e)})


def describe_table(table_name: str) -> str:
    """Returns column names and data types for a given table."""
    try:
        table_name = (table_name or "").strip().split(".")[-1]
        if not _TABLE_NAME.match(table_name):
            return json.dumps({"error": f"Invalid table name: {table_name!r}"})

        client = get_client(readonly=True)
        result = client.query(f"DESCRIBE {settings.clickhouse_database}.{table_name}")
        schema = [{"name": row[0], "type": row[1]} for row in result.result_rows]
        return json.dumps({"table": table_name, "schema": schema})
    except Exception as e:
        return json.dumps({"error": str(e), "table": table_name})


def run_query(sql_query: str) -> str:
    """
    Executes a single read-only query on ClickHouse.
    Records execution latency, row count, and returns up to MAX_ROWS rows.
    """
    original = sql_query or ""
    try:
        # Normalise: strip trailing semicolons/whitespace so the LIMIT we may
        # append does not land after the statement terminator.
        sql = original.strip().rstrip(";").strip()
        if not sql:
            return json.dumps({"error": "Empty query", "raw_query": original})

        lowered = sql.lstrip("(").lstrip()
        if not (lowered[:6].lower() == "select" or lowered[:4].lower() == "with"
                or lowered[:8].lower() == "describe" or lowered[:4].lower() == "show"):
            return json.dumps({
                "error": "Only SELECT / WITH / SHOW / DESCRIBE statements are allowed.",
                "raw_query": original,
            })
        if _FORBIDDEN.search(sql):
            return json.dumps({
                "error": "Query contains a forbidden (non read-only) keyword.",
                "raw_query": original,
            })
        if ";" in sql:
            return json.dumps({"error": "Multiple statements are not allowed.", "raw_query": original})

        # Only append LIMIT when the statement does not already end with one.
        if not _TRAILING_LIMIT.search(sql):
            sql = f"{sql} LIMIT {MAX_ROWS}"

        client = get_client(readonly=True)
        start_time = time.time()
        result = client.query(sql)
        latency_ms = round((time.time() - start_time) * 1000, 2)

        rows = result.result_rows
        column_names = result.column_names
        formatted_rows = [dict(zip(column_names, row)) for row in rows[:MAX_ROWS]]

        return json.dumps({
            "latency_ms": latency_ms,
            "row_count": len(rows),
            "columns": list(column_names),
            "data": formatted_rows,
            "raw_query": sql,
        }, default=str)
    except Exception as e:
        return json.dumps({"error": str(e), "raw_query": original})
