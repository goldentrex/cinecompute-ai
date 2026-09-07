"""Verify the Vertex AI backend before switching the demo over to it.

    GOOGLE_GENAI_USE_VERTEXAI=True \
    GOOGLE_CLOUD_PROJECT=my-project \
    GOOGLE_APPLICATION_CREDENTIALS=/path/key.json \
    python scripts/check_vertex.py

Reports which identity is used, whether Vertex answers, which of the cascade
models exist in the region, and runs one real agent turn end to end.
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.config import settings                                  # noqa: E402
from app.agent.gcp_auth import account_email, ensure_credentials  # noqa: E402
from app.agent.gemini_client import VERTEX_MODELS                 # noqa: E402

OK, FAIL = "  [OK]  ", "  [FAIL]"


def main():
    print("Vertex AI configuration")
    print(f"         use_vertexai : {settings.google_genai_use_vertexai}")
    print(f"         project      : {settings.google_cloud_project or '(unset)'}")
    print(f"         location     : {settings.google_cloud_location}")

    if not settings.google_genai_use_vertexai or not settings.google_cloud_project:
        print(f"{FAIL} set GOOGLE_GENAI_USE_VERTEXAI=True and GOOGLE_CLOUD_PROJECT")
        return 1

    try:
        path = ensure_credentials()
    except RuntimeError as e:
        print(f"{FAIL} {e}")
        return 1
    print(f"{OK} identity: {account_email()}")
    if path:
        print(f"         credentials file: {path}")

    from google import genai
    try:
        client = genai.Client(vertexai=True,
                              project=settings.google_cloud_project,
                              location=settings.google_cloud_location)
    except Exception as e:
        print(f"{FAIL} could not build the Vertex client: {type(e).__name__}: {str(e)[:220]}")
        return 1

    print("\nModel availability at this endpoint")
    usable = []
    for model in VERTEX_MODELS:
        try:
            t = time.time()
            client.models.generate_content(model=model, contents="Reply with OK")
            print(f"{OK} {model:<32} {time.time() - t:.1f}s")
            usable.append(model)
        except Exception as e:
            msg = str(e)
            reason = ("not in this region" if "404" in msg or "NOT_FOUND" in msg else
                      "quota/billing" if "429" in msg or "RESOURCE_EXHAUSTED" in msg else
                      "permission" if "403" in msg or "PERMISSION_DENIED" in msg else
                      msg[:70])
            print(f"         {model:<32} unavailable - {reason}")

    if not usable:
        print(f"\n{FAIL} no model answered. Check that the Vertex AI API is enabled and "
              "the service account has roles/aiplatform.user. Note that Gemini 3 is served "
              "only from GOOGLE_CLOUD_LOCATION=global, not from regional endpoints.")
        return 1

    print(f"\n{OK} {len(usable)} model(s) usable, best is {usable[0]}")

    print("\nOne real agent turn through the ClickHouse MCP server")
    from app.agent.gemini_client import CineComputeAgent
    agent = CineComputeAgent(model_name=usable[0])
    calls = []
    t = time.time()
    answer = agent.process_message("How many render jobs ran on NVIDIA_H100 nodes?",
                                   tool_callback=lambda n, a, r: calls.append(n))
    print(f"{OK} answered in {time.time() - t:.1f}s via {agent.backend} "
          f"({agent.model_name}), {len(calls)} MCP call(s)")
    print(f"         {' '.join(answer.split())[:150]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
