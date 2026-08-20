"""Root entrypoint for MCP Inspector / desktop MCP hosts."""

from src.competitive_intelligence.mcp_server import mcp

if __name__ == "__main__":
    mcp.run(transport="stdio")
