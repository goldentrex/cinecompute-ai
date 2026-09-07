"""Remembers which Gemini models are out of quota today.

Free-tier quota is per model and resets daily at midnight Pacific. Without this,
every new session re-tries each exhausted model in turn before reaching one that
answers - five wasted round-trips and several seconds before a demo even starts.
State is keyed by the Pacific date, so it expires by itself at the reset.
"""
import datetime as dt
import json
import os
import threading

STATE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    ".agent_cache",
)
STATE_FILE = os.path.join(STATE_DIR, "model_state.json")
_lock = threading.Lock()


def pacific_today() -> str:
    """Quota resets on Pacific midnight; PT is UTC-7 (PDT) / UTC-8 (PST)."""
    return (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=8)).strftime("%Y-%m-%d")


def _load():
    try:
        with open(STATE_FILE, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    return data if data.get("date") == pacific_today() else {}


def _save(data):
    try:
        os.makedirs(STATE_DIR, exist_ok=True)
        with open(STATE_FILE, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
    except OSError:
        pass  # best effort: losing this only costs a retry


def mark_exhausted(model: str) -> None:
    with _lock:
        data = _load()
        data["date"] = pacific_today()
        data.setdefault("exhausted", [])
        if model not in data["exhausted"]:
            data["exhausted"].append(model)
        _save(data)


def clear(model: str) -> None:
    """A model that just answered is not exhausted, whatever we thought."""
    with _lock:
        data = _load()
        if model in data.get("exhausted", []):
            data["exhausted"].remove(model)
            data["date"] = pacific_today()
            _save(data)


def exhausted() -> set:
    return set(_load().get("exhausted", []))


def snapshot() -> dict:
    data = _load()
    return {"date": data.get("date", pacific_today()),
            "exhausted": list(data.get("exhausted", []))}
