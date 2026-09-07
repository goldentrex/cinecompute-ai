"""Application Default Credentials for hosts without a filesystem to prepare.

Locally you point GOOGLE_APPLICATION_CREDENTIALS at a key file. On Streamlit
Cloud there is nowhere to put one, so the service account JSON is supplied as a
secret and written to a private temp file once, before any Vertex call.
"""
import json
import os
import tempfile

from app.config import settings

_prepared = False


def ensure_credentials() -> str | None:
    """Return the path to the credentials file in use, or None if not needed."""
    global _prepared

    existing = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if existing and os.path.exists(existing):
        return existing

    raw = (settings.google_credentials_json or "").strip()
    if not raw:
        return None

    if _prepared:
        return os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")

    try:
        parsed = json.loads(raw)
    except ValueError as e:
        hint = ""
        if "control character" in str(e).lower():
            # TOML basic triple quotes turn the \\n escapes inside the private
            # key into real newlines, which JSON then rejects.
            hint = (" The secret was probably quoted with basic triple quotes; "
                    "use literal triple quotes instead.")
        raise RuntimeError(
            "GOOGLE_CREDENTIALS_JSON is not valid JSON - paste the whole service "
            f"account key file, including the braces ({e})." + hint
        ) from e

    fd, path = tempfile.mkstemp(prefix="cinecompute-gcp-", suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(parsed, fh)
    os.chmod(path, 0o600)
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = path
    _prepared = True
    return path


def account_email() -> str:
    """Which identity we are about to authenticate as (for the health check)."""
    raw = (settings.google_credentials_json or "").strip()
    if raw:
        try:
            return json.loads(raw).get("client_email", "unknown")
        except ValueError:
            return "unparseable"
    path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "")
    if path and os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as fh:
                return json.load(fh).get("client_email", "unknown")
        except (OSError, ValueError):
            return "unreadable"
    return "none"
