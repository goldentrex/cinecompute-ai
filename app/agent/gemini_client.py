import json
import time
from google import genai
from google.genai import types
from app.config import settings
from app.agent.mcp_bridge import list_tables, describe_table, run_query
from app.agent.prompts import SYSTEM_INSTRUCTION
from app.agent import cache

# Explicit declarations instead of raw callables: the SDK would otherwise run
# Automatic Function Calling and execute the tools itself, which bypasses our
# loop and leaves the Live MCP Query Inspector empty.
TOOL_DECLARATIONS = [
    types.FunctionDeclaration(
        name="list_tables",
        description="List the tables available in the render farm telemetry database.",
        parameters=types.Schema(type=types.Type.OBJECT, properties={}),
    ),
    types.FunctionDeclaration(
        name="describe_table",
        description="Return the column names and ClickHouse data types of a table.",
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={
                "table_name": types.Schema(
                    type=types.Type.STRING,
                    description="Table name without database prefix, e.g. vfx_render_events.",
                )
            },
            required=["table_name"],
        ),
    ),
    types.FunctionDeclaration(
        name="run_query",
        description=(
            "Execute a single read-only ClickHouse SELECT statement and return up to "
            "50 rows as JSON, together with server-side latency and row count."
        ),
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={
                "sql_query": types.Schema(
                    type=types.Type.STRING,
                    description=(
                        "A ClickHouse SQL SELECT statement. Fully qualify tables as "
                        f"{settings.clickhouse_database}.<table>. No semicolon, no DDL, no DML."
                    ),
                )
            },
            required=["sql_query"],
        ),
    ),
]

MAX_TOOL_ROUNDS = 10

# Free-tier daily quotas are per-model, so keep alternates ready: if the primary
# model returns 429 mid-demo we transparently continue on the next one.
# Ordered best-first. Each entry has its OWN free-tier daily allowance, so a
# long chain multiplies the number of demo runs available without billing.
FALLBACK_MODELS = [
    "gemini-3.8-flash",
    "gemini-3.7-flash",
    "gemini-3.6-flash",
    "gemini-3.5-flash",
    "gemini-3-flash-preview",
    "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite",
]


class CineComputeAgent:
    def __init__(self, model_name: str = None):
        self.client = genai.Client(api_key=settings.gemini_api_key)
        self.model_name = model_name or settings.gemini_model
        self.dispatch = {
            "list_tables": list_tables,
            "describe_table": describe_table,
            "run_query": run_query,
        }
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

    def _generate(self, contents, config):
        """generate_content with one retry, then failover to an alternate model.

        A model that is out of quota (429) or retired (404) is gone for the day,
        so the session sticks to whichever fallback works. A capacity blip (503)
        is not a reason to spend the rest of the demo on a weaker model, so that
        switch is temporary and the preferred model is tried again next turn.
        """
        candidates = [self.model_name] + [m for m in FALLBACK_MODELS if m != self.model_name]
        preferred = candidates[0]
        last_exc = None
        sticky = True

        for model in candidates:
            for attempt in range(2):
                try:
                    response = self.client.models.generate_content(
                        model=model, contents=contents, config=config
                    )
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
                # MCP inspector fills in exactly as it did on the live run.
                for call in recorded.get("tool_calls", []):
                    if tool_callback:
                        tool_callback(call["name"], call.get("args", {}), call["result"])
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
        contents = self.history.copy()
        contents.append(types.Content(role="user", parts=[types.Part.from_text(text=user_message)]))

        config = types.GenerateContentConfig(
            system_instruction=self.system_instruction,
            tools=[types.Tool(function_declarations=TOOL_DECLARATIONS)],
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

                fn = self.dispatch.get(name)
                if fn is None:
                    result_str = json.dumps({"error": f"Unknown tool: {name}"})
                else:
                    try:
                        result_str = fn(**args)
                    except Exception as e:  # never break the loop on a tool error
                        result_str = json.dumps({"error": f"{type(e).__name__}: {e}"})

                if tool_callback:
                    tool_callback(name, args, result_str)

                try:
                    result_dict = json.loads(result_str)
                except Exception:
                    result_dict = {"result": result_str}
                if not isinstance(result_dict, dict):
                    result_dict = {"result": result_dict}

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
