"""
Model Context Protocol (MCP) - Server and client integration
Inspired by: modelcontextprotocol, modelcontextprotocol/servers,
composio/dev, openinterpreter/open-interpreter
"""
from fastapi import APIRouter, Depends, HTTPException, status, Query
from typing import List, Optional, Dict, Any
from datetime import datetime
import uuid
import json
import os
import httpx

from app.auth import get_current_active_user
from app.models import User

router = APIRouter(prefix="/api/mcp", tags=["Model Context Protocol"])

# ============================================================
# MCP SERVERS REGISTRY
# ============================================================

MCP_SERVERS = {
    "filesystem": {
        "name": "Filesystem MCP Server",
        "description": "Secure file system access for AI agents",
        "command": "npx @modelcontextprotocol/server-filesystem",
        "capabilities": ["read", "write", "list", "search"],
        "github": "https://github.com/modelcontextprotocol/servers",
    },
    "github": {
        "name": "GitHub MCP Server",
        "description": "GitHub repository and issue management",
        "command": "npx @modelcontextprotocol/server-github",
        "capabilities": ["repos", "issues", "pulls", "search"],
        "github": "https://github.com/modelcontextprotocol/servers",
    },
    "postgres": {
        "name": "PostgreSQL MCP Server",
        "description": "Database access for AI agents",
        "command": "npx @modelcontextprotocol/server-postgres",
        "capabilities": ["query", "schema", "insert", "update"],
        "github": "https://github.com/modelcontextprotocol/servers",
    },
    "sqlite": {
        "name": "SQLite MCP Server",
        "description": "SQLite database access",
        "command": "npx @modelcontextprotocol/server-sqlite",
        "capabilities": ["query", "schema"],
        "github": "https://github.com/modelcontextprotocol/servers",
    },
    "fetch": {
        "name": "Fetch MCP Server",
        "description": "HTTP fetch for AI agents",
        "command": "npx @modelcontextprotocol/server-fetch",
        "capabilities": ["get", "post", "web_scraping"],
        "github": "https://github.com/modelcontextprotocol/servers",
    },
    "memory": {
        "name": "Memory MCP Server",
        "description": "Persistent memory for AI agents",
        "command": "npx @modelcontextprotocol/server-memory",
        "capabilities": ["store", "retrieve", "search"],
        "github": "https://github.com/modelcontextprotocol/servers",
    },
    "brave-search": {
        "name": "Brave Search MCP",
        "description": "Web search via Brave Search API",
        "command": "npx @modelcontextprotocol/server-brave-search",
        "capabilities": ["web_search", "news"],
        "github": "https://github.com/modelcontextprotocol/servers",
    },
    "slack": {
        "name": "Slack MCP Server",
        "description": "Slack workspace access",
        "command": "npx @modelcontextprotocol/server-slack",
        "capabilities": ["messages", "channels", "users"],
        "github": "https://github.com/modelcontextprotocol/servers",
    },
    "everything": {
        "name": "Everything MCP Server",
        "description": "Local file search (Windows/macOS)",
        "command": "npx @modelcontextprotocol/server-everything",
        "capabilities": ["file_search", "content_search"],
        "github": "https://github.com/modelcontextprotocol/servers",
    },
    "sequential-thinking": {
        "name": "Sequential Thinking MCP",
        "description": "Structured reasoning for complex problems",
        "command": "npx @modelcontextprotocol/server-sequential-thinking",
        "capabilities": ["reasoning", "planning", "decomposition"],
        "github": "https://github.com/modelcontextprotocol/servers",
    },
    "puppeteer": {
        "name": "Puppeteer MCP Server",
        "description": "Browser automation via MCP",
        "command": "npx @modelcontextprotocol/server-puppeteer",
        "capabilities": ["browse", "screenshot", "click", "type"],
        "github": "https://github.com/modelcontextprotocol/servers",
    },
}


@router.get("/servers")
async def list_mcp_servers():
    """List available MCP servers"""
    return {"servers": MCP_SERVERS, "total": len(MCP_SERVERS)}


@router.get("/servers/{server_name}/capabilities")
async def get_mcp_server_capabilities(
    server_name: str,
    current_user: User = Depends(get_current_active_user),
):
    """Get capabilities of an MCP server"""
    if server_name not in MCP_SERVERS:
        raise HTTPException(status_code=404, detail="MCP server not found")
    return {"server": server_name, **MCP_SERVERS[server_name]}


# ============================================================
# MCP CLIENT CONNECTIONS
# ============================================================

MCP_CONNECTIONS_STORE: Dict[str, Dict[str, Any]] = {}


@router.post("/connect", status_code=status.HTTP_201_CREATED)
async def connect_mcp_server(
    server_name: str,
    config: Optional[Dict[str, Any]] = None,
    current_user: User = Depends(get_current_active_user),
):
    """Connect to an MCP server"""
    if server_name not in MCP_SERVERS:
        raise HTTPException(status_code=400, detail=f"Invalid server. Options: {list(MCP_SERVERS.keys())}")

    connection_id = str(uuid.uuid4())
    connection = {
        "id": connection_id,
        "server_name": server_name,
        "server_info": MCP_SERVERS[server_name],
        "config": config or {},
        "owner_id": current_user.id,
        "connected_at": datetime.utcnow().isoformat(),
        "status": "connected",
        "tools": [],
        "resources": [],
    }

    # Mock available tools based on server capabilities
    capabilities = MCP_SERVERS[server_name].get("capabilities", [])
    for cap in capabilities:
        connection["tools"].append({
            "name": f"{server_name}_{cap}",
            "description": f"{cap} capability via {server_name}",
            "input_schema": {"type": "object", "properties": {}},
        })

    MCP_CONNECTIONS_STORE[connection_id] = connection

    return {
        "connection_id": connection_id,
        "server_name": server_name,
        "status": "connected",
        "tools": connection["tools"],
        "capabilities": capabilities,
    }


@router.get("/connections")
async def list_mcp_connections(
    current_user: User = Depends(get_current_active_user),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
):
    """List user's MCP connections"""
    connections = [
        c for c in MCP_CONNECTIONS_STORE.values() if c["owner_id"] == current_user.id
    ]
    return {
        "connections": connections[skip:skip + limit],
        "total": len(connections),
    }


@router.get("/connections/{connection_id}")
async def get_mcp_connection(
    connection_id: str,
    current_user: User = Depends(get_current_active_user),
):
    """Get MCP connection details"""
    if connection_id not in MCP_CONNECTIONS_STORE:
        raise HTTPException(status_code=404, detail="MCP connection not found")

    connection = MCP_CONNECTIONS_STORE[connection_id]
    if connection["owner_id"] != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    return connection


@router.delete("/connections/{connection_id}", status_code=status.HTTP_204_NO_CONTENT)
async def disconnect_mcp_server(
    connection_id: str,
    current_user: User = Depends(get_current_active_user),
):
    """Disconnect from an MCP server"""
    if connection_id not in MCP_CONNECTIONS_STORE:
        raise HTTPException(status_code=404, detail="MCP connection not found")

    connection = MCP_CONNECTIONS_STORE[connection_id]
    if connection["owner_id"] != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    connection["status"] = "disconnected"
    connection["disconnected_at"] = datetime.utcnow().isoformat()


# ============================================================
# MCP TOOL CALLING
# ============================================================

@router.post("/connections/{connection_id}/tools/{tool_name}/call")
async def call_mcp_tool(
    connection_id: str,
    tool_name: str,
    arguments: Dict[str, Any],
    current_user: User = Depends(get_current_active_user),
):
    """Call a tool on an MCP server"""
    if connection_id not in MCP_CONNECTIONS_STORE:
        raise HTTPException(status_code=404, detail="MCP connection not found")

    connection = MCP_CONNECTIONS_STORE[connection_id]
    if connection["owner_id"] != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    if connection["status"] != "connected":
        raise HTTPException(status_code=400, detail="MCP connection not active")

    # Find the tool
    tool = None
    for t in connection.get("tools", []):
        if t["name"] == tool_name:
            tool = t
            break

    if not tool:
        raise HTTPException(status_code=404, detail=f"Tool '{tool_name}' not found on this server")

    # Mock tool execution
    return {
        "connection_id": connection_id,
        "tool_name": tool_name,
        "arguments": arguments,
        "result": {
            "success": True,
            "message": f"Tool {tool_name} executed on {connection['server_name']}",
            "data": {},
        },
        "executed_at": datetime.utcnow().isoformat(),
    }


# ============================================================
# MCP RESOURCES
# ============================================================

@router.get("/connections/{connection_id}/resources")
async def list_mcp_resources(
    connection_id: str,
    current_user: User = Depends(get_current_active_user),
):
    """List resources available from an MCP server"""
    if connection_id not in MCP_CONNECTIONS_STORE:
        raise HTTPException(status_code=404, detail="MCP connection not found")

    connection = MCP_CONNECTIONS_STORE[connection_id]
    if connection["owner_id"] != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    server_name = connection["server_name"]
    mock_resources = {
        "filesystem": [
            {"uri": "file:///home/user/documents", "name": "Documents", "mimeType": "inode/directory"},
            {"uri": "file:///home/user/downloads", "name": "Downloads", "mimeType": "inode/directory"},
        ],
        "github": [
            {"uri": "github://repos", "name": "Repositories", "mimeType": "application/json"},
        ],
        "postgres": [
            {"uri": "postgres://database/tables", "name": "Database Tables", "mimeType": "application/json"},
        ],
    }.get(server_name, [])

    return {
        "connection_id": connection_id,
        "server_name": server_name,
        "resources": mock_resources,
        "total": len(mock_resources),
    }


# ============================================================
# MCP PROMPTS
# ============================================================

@router.get("/connections/{connection_id}/prompts")
async def list_mcp_prompts(
    connection_id: str,
    current_user: User = Depends(get_current_active_user),
):
    """List prompts/templates from an MCP server"""
    if connection_id not in MCP_CONNECTIONS_STORE:
        raise HTTPException(status_code=404, detail="MCP connection not found")

    connection = MCP_CONNECTIONS_STORE[connection_id]
    if connection["owner_id"] != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    return {
        "connection_id": connection_id,
        "server_name": connection["server_name"],
        "prompts": [],
        "total": 0,
        "note": "Server-specific prompts would be listed here",
    }


# ============================================================
# COMPOSIO INTEGRATION (Agent tool connections)
# ============================================================

@router.post("/composio/connect")
async def connect_composio(
    tool_name: str,
    api_key: Optional[str] = None,
    current_user: User = Depends(get_current_active_user),
):
    """Connect to a tool via Composio"""
    return {
        "tool": tool_name,
        "platform": "composio",
        "status": "connected",
        "connection_id": str(uuid.uuid4()),
        "auth_url": "https://composio.dev/connect",
        "note": "Composio handles OAuth and auth for 100+ tools",
    }


@router.get("/composio/tools")
async def list_composio_tools(
    current_user: User = Depends(get_current_active_user),
):
    """List available tools via Composio"""
    return {
        "tools": [
            {"name": "gmail_send_email", "description": "Send email via Gmail"},
            {"name": "github_create_issue", "description": "Create GitHub issue"},
            {"name": "slack_send_message", "description": "Send Slack message"},
            {"name": "youtube_upload_video", "description": "Upload video to YouTube"},
            {"name": "google_sheets_append", "description": "Append to Google Sheets"},
        ],
        "total": 5,
        "platform": "composio",
    }