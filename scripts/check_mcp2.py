import inspect

from mcp.server.mcpserver import MCPServer

print([x for x in dir(MCPServer) if not x.startswith("_")])
sig = getattr(MCPServer, "__init__", None)
print(inspect.signature(MCPServer.__init__))
