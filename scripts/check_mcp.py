from pathlib import Path

import mcp
print("mcp", mcp.__version__ if hasattr(mcp, "__version__") else dir(mcp)[:20])
try:
    from mcp.server.mcpserver import MCPServer
    print("MCPServer", MCPServer)
except Exception as exc:
    print("err", exc)
