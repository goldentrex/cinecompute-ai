import sys
import os
import json

# Add parent directory to path to import app modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.agent.mcp_bridge import list_tables, describe_table, run_query
from app.agent.gemini_client import CineComputeAgent

def test_mcp_bridge():
    print("--- TESTING MCP BRIDGE ---")
    tables = list_tables()
    print("Tables:", tables)
    
    schema = describe_table("vfx_render_events")
    print("Schema for vfx_render_events:", schema)
    
    # Test readonly=1 safety
    try:
        # A simple query
        res = run_query("SELECT count(*) FROM cinecompute.vfx_render_events")
        print("Count Query Result:", res)
    except Exception as e:
        print("Error on run_query:", e)
        
    print("--------------------------\n")

def test_gemini_agent():
    print("--- TESTING GEMINI AGENT ---")
    agent = CineComputeAgent()
    
    def tool_callback(name, args, result):
        print(f"🔧 TOOL CALLED: {name}")
        print(f"   Args: {args}")
        print(f"   Result Length: {len(result)} chars")
        
    prompt = "Quelle séquence a généré le plus d'erreurs OOM_KILLED ?"
    print(f"USER: {prompt}")
    
    response = agent.process_message(prompt, tool_callback=tool_callback)
    print("\nFINAL RESPONSE:")
    print(response)
    print("----------------------------\n")

if __name__ == "__main__":
    test_mcp_bridge()
    test_gemini_agent()
