"""On-disk replay cache for agent answers.

Free-tier Gemini quota is per-model and per-day, and rehearsing a demo burns it
fast: every tool round is a separate API request. This cache lets a recorded run
be replayed for zero quota, so the live quota is spent on the take that counts.

Modes (env var AGENT_CACHE_MODE):
    off    - always call the API, never read or write the cache (default)
    record - call the API, then save the run for later replay
    replay - replay a saved run when one exists, otherwise call the API and save

A replayed answer is always flagged so it is never mistaken for a live run.
"""
import hashlib
import json
import os
import time

CACHE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    ".agent_cache",
)


def mode() -> str:
    return os.environ.get("AGENT_CACHE_MODE", "off").strip().lower()


def _key(question: str) -> str:
    return hashlib.sha256(" ".join(question.split()).lower().encode()).hexdigest()[:16]


def _path(question: str) -> str:
    return os.path.join(CACHE_DIR, f"{_key(question)}.json")


def load(question: str):
    """Return a recorded run for this question, or None."""
    try:
        with open(_path(question), "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def save(question: str, answer: str, tool_calls, model: str) -> None:
    """Record a run. tool_calls is a list of (name, args, result_str) tuples."""
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        payload = {
            "question": question,
            "answer": answer,
            "model": model,
            "recorded_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "tool_calls": [
                {"name": n, "args": a, "result": r} for n, a, r in tool_calls
            ],
        }
        with open(_path(question), "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, default=str)
    except OSError:
        pass  # caching is best-effort; never break a demo over it


def list_cached():
    """Return [(question, recorded_at, model)] for every recorded run."""
    out = []
    try:
        for name in sorted(os.listdir(CACHE_DIR)):
            if not name.endswith(".json"):
                continue
            try:
                with open(os.path.join(CACHE_DIR, name), encoding="utf-8") as fh:
                    d = json.load(fh)
            except (OSError, ValueError):
                continue
            # the directory also holds model_state.json, which is not a run
            if not isinstance(d, dict) or not d.get("question"):
                continue
            out.append((d["question"], d.get("recorded_at", ""), d.get("model", "")))
    except OSError:
        pass
    return out
