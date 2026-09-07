import json
import os
import time
from google import genai
from google.genai import types
from app.config import settings
from app.agent.mcp_client import ClickHouseMCP, run_async
from app.agent.prompts import SYSTEM_INSTRUCTION
from app.agent import cache, model_state

# The tool list is no longer written here: it is discovered from the ClickHouse
# MCP server at `tools/list`, so the agent can only call what the server offers.

# Keys added for the inspector that must never reach the model, to stop it
# mistaking database metrics for business figures.
UI_ONLY_KEYS = {"latency_ms", "roundtrip_ms", "rows_scanned"}

MAX_ROWS = 50
MAX_TOOL_ROUNDS = 10

# Free-tier daily quotas are per-model, so keep alternates ready: if the primary
# model returns 429 mid-demo we transparently continue on the next one.
# Ordered best-first. Each entry has its OWN free-tier daily allowance, so a
# long chain multiplies the number of demo runs available without billing.
# Vertex and AI Studio expose different catalogues to this project: every 3.x
# model returns 404 "no access" on Vertex, while 2.5-flash is retired on AI
# Studio. Measured, not assumed - see scripts/check_vertex.py.
VERTEX_MODELS = [
    "gemini-2.5-flash",
    "gemini-2.5-pro",
    "gemini-2.5-flash-lite",
]

FALLBACK_MODELS = [
    "gemini-3.8-flash",
    "gemini-3.7-flash",
    "gemini-3.6-flash",
    "gemini-3.5-flash",
    "gemini-3-flash-preview",
    "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite",
    "gemini-3.1-flash-lite-preview",
]


def _wrap_mcp_result(name, args, payload, elapsed_ms, failed):
    """Normalise an MCP tool result into the shape the inspector expects.

    mcp-clickhouse answers `run_query` with {"columns": [...], "rows": [[...]]};
    the UI wants named rows, a row count and a latency, while the model must see
    only the data.
    """
    if failed:
        return json.dumps({"error": payload[:600], "raw_query": (args or {}).get("query", "")})

    try:
        data = json.loads(payload)
    except Exception:
        return json.dumps({"result": payload[:4000], "latency_ms": round(elapsed_ms, 2)})

    out = {"latency_ms": round(elapsed_ms, 2)}
    if isinstance(data, dict) and "columns" in data and "rows" in data:
        cols, rows = data["columns"], data["rows"]
        out.update({
            "columns": cols,
            "row_count": len(rows),
            "data": [dict(zip(cols, r)) for r in rows[:MAX_ROWS]],
            "raw_query": (args or {}).get("query", ""),
        })
    elif isinstance(data, list):
        out.update({"row_count": len(data), "data": data[:MAX_ROWS]})
    else:
        out.update({"result": data})
    return json.dumps(out, default=str)


class CineComputeAgent:
    def __init__(self, model_name: str = None):
        # Vertex AI when a Google Cloud project is configured (no per-model free
        # quota), otherwise the AI Studio endpoint with an API key.
        if settings.google_genai_use_vertexai and settings.google_cloud_project:
            from app.agent.gcp_auth import ensure_credentials
            ensure_credentials()
            self.client = genai.Client(
                vertexai=True,
                project=settings.google_cloud_project,
                location=settings.google_cloud_location,
            )
            self.backend = "vertex"
        else:
            self.client = genai.Client(api_key=settings.gemini_api_key)
            self.backend = "ai-studio"

        self.model_name = model_name or settings.gemini_model
        # the configured default is an AI-Studio model id; Vertex exposes a
        # different catalogue to this project, so fall back to one it serves
        if self.backend == "vertex" and self.model_name not in VERTEX_MODELS:
            self.model_name = VERTEX_MODELS[0]
        self.system_instruction = SYSTEM_INSTRUCTION
        self.history = []
        self.last_error = None

    RETRY_DELAY_SEC = 2

    @staticmethod
    def _classify(exc):
        """quota (gone for the day) / retired / transient (retry) / fatal."""
        code = getattr(exc, "code", None)
        msg = str(exc)
        if code == 429 or "RESOURCE_EXHAUSTED" in msg:
            return "quota"
        if code == 404 or "NOT_FOUND" in msg:
            return "retired"
        if code in (500, 503, 504) or any(
            t in msg for t in ("UNAVAILABLE", "INTERNAL", "DEADLINE_EXCEEDED")
        ):
            return "transient"
        return "fatal"

    def candidates(self):
        """Preferred model first, then fallbacks, skipping today's known-dry ones.

        Vertex has no per-model free quota, so the memo only applies to AI Studio.
        The preferred model is always tried, even if marked, in case quota reset.
        """
        pool = VERTEX_MODELS if self.backend == "vertex" else FALLBACK_MODELS
        ordered = [self.model_name] + [m for m in pool if m != self.model_name]
        if self.backend != "ai-studio":
            return ordered
        dry = model_state.exhausted()
        live = [m for m in ordered if m not in dry or m == ordered[0]]
        return live or ordered

    def _generate(self, contents, config):
        """generate_content with one retry, then failover to an alternate model.

        A model that is out of quota (429) or retired (404) is gone for the day and
        is remembered as such, so later turns do not pay for the discovery again. A
        capacity blip (503) is retried once and does not permanently downgrade the
        session.
        """
        candidates = self.candidates()
        preferred = candidates[0]
        last_exc = None
        sticky = True

        for model in candidates:
            for attempt in range(2):
                try:
                    response = self.client.models.generate_content(
                        model=model, contents=contents, config=config
                    )
                    model_state.clear(model)
                    if model != self.model_name and sticky:
                        self.model_name = model
                    return response
                except Exception as e:
                    last_exc = e
                    kind = self._classify(e)
                    if kind == "fatal":
                        raise
                    if kind == "transient" and attempt == 0:
                        time.sleep(self.RETRY_DELAY_SEC)
                        continue  # same model, one more go
                    if kind in ("quota", "retired") and self.backend == "ai-studio":
                        model_state.mark_exhausted(model)
                    if model == preferred and kind == "transient":
                        sticky = False
                    break

        raise last_exc

    def process_message(self, user_message: str, tool_callback=None):
        """
        tool_callback is a function(tool_name, tool_args, tool_result) used to update UI.
        Never raises: transport/quota failures are returned as readable text so the UI stays alive.
        """
        self.last_error = None
        self.replayed = False

        cache_mode = cache.mode()
        if cache_mode == "replay":
            recorded = cache.load(user_message)
            if recorded:
                # Replay the recorded tool calls through the same callback so the
                # pipeline and inspector fill in as they did on the live run. A
                # small pace keeps that visible; set REPLAY_STEP_DELAY=0 to skip.
                delay = float(os.environ.get("REPLAY_STEP_DELAY", "0.45"))
                for call in recorded.get("tool_calls", []):
                    if tool_callback:
                        tool_callback(call["name"], call.get("args", {}), call["result"])
                        if delay:
                            time.sleep(delay)
                self.replayed = True
                self.model_name = recorded.get("model", self.model_name)
                return recorded["answer"]

        recorded_calls = []

        def wrapped_callback(name, args, result_str):
            recorded_calls.append((name, args, result_str))
            if tool_callback:
                tool_callback(name, args, result_str)

        try:
            answer = self._process_message(user_message, wrapped_callback)
            if cache_mode in ("record", "replay") and not answer.startswith("**Agent unavailable"):
                cache.save(user_message, answer, recorded_calls, self.model_name)
            return answer
        except Exception as e:
            self.last_error = f"{type(e).__name__}: {e}"
            return (
                "**Agent unavailable.**\n\n"
                f"`{type(e).__name__}` while calling the Gemini API:\n\n```\n{str(e)[:600]}\n```"
            )

    def _process_message(self, user_message: str, tool_callback=None):
        """Open an MCP session for the turn and run the loop inside it."""
        return run_async(self._turn(user_message, tool_callback))

    async def _turn(self, user_message: str, tool_callback=None):
        async with ClickHouseMCP() as mcp:
            return await self._loop(mcp, user_message, tool_callback)

    async def _loop(self, mcp, user_message: str, tool_callback=None):
        contents = self.history.copy()
        contents.append(types.Content(role="user", parts=[types.Part.from_text(text=user_message)]))

        config = types.GenerateContentConfig(
            system_instruction=self.system_instruction,
            tools=[types.Tool(function_declarations=mcp.declarations)],
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            temperature=0.2,
        )

        response = None
        for _ in range(MAX_TOOL_ROUNDS):
            response = self._generate(contents, config)

            if not (response.candidates and response.candidates[0].content):
                break
            contents.append(response.candidates[0].content)

            calls = response.function_calls
            if not calls:
                break

            function_responses = []
            for function_call in calls:
                name = function_call.name
                args = dict(function_call.args or {})

                payload, elapsed_ms, failed = await mcp.call(name, args)
                result_str = _wrap_mcp_result(name, args, payload, elapsed_ms, failed)

                if tool_callback:
                    tool_callback(name, args, result_str)

                try:
                    result_dict = json.loads(result_str)
                except Exception:
                    result_dict = {"result": result_str}
                if not isinstance(result_dict, dict):
                    result_dict = {"result": result_dict}
                else:
                    # Engine telemetry is for the inspector, not the model: it once
                    # reported `rows_scanned` (173,728) as the number of render
                    # tasks in a sequence (83,485). The model only sees the data.
                    result_dict = {k: v for k, v in result_dict.items()
                                   if k not in UI_ONLY_KEYS}

                function_responses.append(
                    types.Part.from_function_response(name=name, response=result_dict)
                )

            contents.append(types.Content(role="user", parts=function_responses))

        text = getattr(response, "text", None) if response is not None else None

        if not text:
            # The model ran out of tool rounds (or returned no prose). Ask once
            # more with tools disabled so the demo always ends on an answer.
            try:
                final = self._generate(
                    contents + [types.Content(
                        role="user",
                        parts=[types.Part.from_text(text=(
                            "Stop querying. Using only the data already retrieved above, "
                            "write your final answer now in the 3 required sections."
                        ))],
                    )],
                    types.GenerateContentConfig(
                        system_instruction=self.system_instruction,
                        temperature=0.2,
                    ),
                )
                if final.candidates and final.candidates[0].content:
                    contents.append(final.candidates[0].content)
                text = getattr(final, "text", None)
            except Exception as e:
                text = f"Agent error while composing the final answer: {e}"

        self.history = contents
        return text or "No response generated."
