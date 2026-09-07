"""Remembers which Gemini models are out of quota, for a short while.

Without this, every session re-tries each exhausted model before reaching one
that answers. The memo was first keyed on the Pacific date, on the assumption
that free-tier quota resets at Pacific midnight - but quota was observed coming
back while the Pacific date had not changed, which would have made the memo skip
models that were available again. So an entry simply expires after RETRY_AFTER
and the model is tried once more: wrong either way, the cost is one 0.6s call.
"""
import json
import os
import threading
import time

STATE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    ".agent_cache",
)
STATE_FILE = os.path.join(STATE_DIR, "model_state.json")
# long enough to spare a demo the repeated discovery, short enough that a model
# whose quota came back is picked up again quickly
RETRY_AFTER = float(os.environ.get("MODEL_RETRY_AFTER_SEC", "1800"))
_lock = threading.Lock()


def _load():
    """Entries older than RETRY_AFTER are dropped, so the memo self-heals."""
    try:
        with open(STATE_FILE, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    now = time.time()
    marks = {m: ts for m, ts in (data.get("marks") or {}).items()
             if now - ts < RETRY_AFTER}
    return {"marks": marks}


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
        data.setdefault("marks", {})[model] = time.time()
        _save(data)


def clear(model: str) -> None:
    """A model that just answered is not exhausted, whatever we thought."""
    with _lock:
        data = _load()
        if data.get("marks", {}).pop(model, None) is not None:
            _save(data)


def exhausted() -> set:
    return set(_load().get("marks", {}))


def snapshot() -> dict:
    now = time.time()
    return {"retry_after_sec": RETRY_AFTER,
            "skipped": {m: f"{now - ts:.0f}s ago"
                        for m, ts in _load().get("marks", {}).items()}}
