"""Client for the official ClickHouse MCP server (mcp-clickhouse).

The agent reaches ClickHouse only through this server, spoken to over MCP's
stdio transport: the process is launched per turn, `initialize` negotiates the
session, `tools/list` discovers what it offers, and every query the model writes
goes out as a `tools/call`. Nothing here talks to the database directly.
"""
import asyncio
import os
import shutil
import sys
import time

from google.genai import types
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from app.config import settings

# Writes are refused twice over: the server opens ClickHouse with readonly=1,
# and this allowlist rejects anything that is not a read before it is sent.
READ_PREFIXES = ("select", "with", "show", "describe", "desc", "explain")


def server_command():
    """Path to the mcp-clickhouse executable that ships with this environment."""
    local = os.path.join(os.path.dirname(sys.executable), "mcp-clickhouse")
    return local if os.path.exists(local) else (shutil.which("mcp-clickhouse") or "mcp-clickhouse")


def server_env():
    """mcp-clickhouse reads its connection from the environment."""
    env = dict(os.environ)
    env.update({
        "CLICKHOUSE_HOST": settings.clickhouse_host,
        "CLICKHOUSE_PORT": str(settings.clickhouse_port),
        "CLICKHOUSE_USER": settings.clickhouse_user,
        "CLICKHOUSE_PASSWORD": settings.clickhouse_password,
        "CLICKHOUSE_DATABASE": settings.clickhouse_database,
        "CLICKHOUSE_SECURE": str(settings.clickhouse_secure).lower(),
        "CLICKHOUSE_VERIFY": str(settings.clickhouse_verify).lower(),
    })
    return env


def _schema(node):
    """JSON Schema (as published by the MCP server) -> google-genai Schema."""
    if not isinstance(node, dict):
        return types.Schema(type=types.Type.STRING)

    kinds = {"string": types.Type.STRING, "integer": types.Type.INTEGER,
             "number": types.Type.NUMBER, "boolean": types.Type.BOOLEAN,
             "array": types.Type.ARRAY, "object": types.Type.OBJECT}
    raw = node.get("type")
    if isinstance(raw, list):                      # e.g. ["string", "null"]
        raw = next((t for t in raw if t != "null"), "string")
    kind = kinds.get(raw, types.Type.STRING)

    if kind is types.Type.OBJECT:
        props = {k: _schema(v) for k, v in (node.get("properties") or {}).items()}
        return types.Schema(type=kind, properties=props,
                            required=node.get("required") or None,
                            description=node.get("description"))
    if kind is types.Type.ARRAY:
        return types.Schema(type=kind, items=_schema(node.get("items") or {}),
                            description=node.get("description"))
    return types.Schema(type=kind, description=node.get("description"))


def declarations_from(tools):
    """Turn the server's advertised tools into Gemini function declarations."""
    out = []
    for t in tools:
        schema = _schema(t.input_schema or {"type": "object", "properties": {}})
        out.append(types.FunctionDeclaration(
            name=t.name,
            description=(t.description or t.name).strip()[:900],
            parameters=schema,
        ))
    return out


class ClickHouseMCP:
    """An initialised MCP session, held open for the duration of one turn."""

    def __init__(self):
        self.session = None
        self.tools = []
        self._stack = None

    async def __aenter__(self):
        from contextlib import AsyncExitStack
        self._stack = AsyncExitStack()
        params = StdioServerParameters(command=server_command(), args=[], env=server_env())
        read, write = await self._stack.enter_async_context(stdio_client(params))
        self.session = await self._stack.enter_async_context(ClientSession(read, write))
        await self.session.initialize()
        self.tools = (await self.session.list_tools()).tools
        return self

    async def __aexit__(self, *exc):
        await self._stack.aclose()
        return False

    @property
    def declarations(self):
        return declarations_from(self.tools)

    async def call(self, name, args):
        """Run one MCP tool call, returning (payload_text, elapsed_ms, is_error)."""
        query = (args or {}).get("query", "")
        if name == "run_query" and query:
            head = query.strip().lstrip("(").lstrip().split(None, 1)[0].lower()
            if head not in READ_PREFIXES:
                return f"Refused: only read statements are allowed, got '{head}'.", 0.0, True
            if ";" in query.strip().rstrip(";"):
                return "Refused: multiple statements are not allowed.", 0.0, True

        start = time.time()
        try:
            result = await self.session.call_tool(name, args or {})
        except Exception as e:
            return f"{type(e).__name__}: {e}", (time.time() - start) * 1000, True
        elapsed = (time.time() - start) * 1000
        text = "".join(getattr(c, "text", "") for c in (result.content or []))
        return text, elapsed, bool(result.is_error)


def run_async(coro):
    """Run a coroutine from Streamlit's synchronous script thread."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    # a loop is already running (rare here): give the coroutine its own thread
    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(1) as pool:
        return pool.submit(asyncio.run, coro).result()
