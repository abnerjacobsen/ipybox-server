#!/usr/bin/env python3
"""
MCP Proxy Demo Script

This script demonstrates how to use the MCP Proxy endpoints in the ipybox-server.
It shows both synchronous (requests) and asynchronous (aiohttp) approaches to
interacting with MCP servers through the proxy.

The demo covers:
1. Creating a container
2. Making MCP requests using the Streamable HTTP protocol
3. Both JSON and SSE response formats
4. Session management with proper headers
5. Standard MCP lifecycle (initialize, list tools, call tools)
6. Error handling and cleanup

For more information on the Model Context Protocol (MCP), see:
https://modelcontextprotocol.io/
"""

import asyncio
import json
import os
import sys
import time
from typing import Any, Dict, List, Optional, Union

import aiohttp
import requests
from requests.exceptions import RequestException

# Configuration
SERVER_URL = "http://localhost:8000"  # ipybox server URL
API_KEY = os.environ.get("IPYBOX_API_KEY", "")  # API key for authentication
DEFAULT_TAG = "ghcr.io/gradion-ai/ipybox"  # Default Docker image tag

# JSON-RPC 2.0 request templates
INITIALIZE_REQUEST = {
    "jsonrpc": "2.0",
    "method": "initialize",
    "params": {
        "protocol_version": "2025-03-26",
        "client_info": {
            "name": "mcp_proxy_demo",
            "version": "1.0.0"
        },
        "capabilities": {
            "tools": True,
            "resources": True,
            "prompts": False,
            "completions": False,
            "sampling": False
        }
    },
    "id": 1
}

TOOLS_LIST_REQUEST = {
    "jsonrpc": "2.0",
    "method": "tools/list",
    "id": 2
}

TOOLS_CALL_REQUEST_TEMPLATE = {
    "jsonrpc": "2.0",
    "method": "tools/call",
    "params": {
        "tool_name": "",  # To be filled in
        "params": {}      # To be filled in
    },
    "id": 3
}

# Headers
def get_headers(api_key: Optional[str] = None, session_id: Optional[str] = None, use_sse: bool = False) -> Dict[str, str]:
    """Generate headers for API requests."""
    headers = {}
    
    # API key authentication
    if api_key:
        headers["X-API-Key"] = api_key
    
    # Content type
    headers["Content-Type"] = "application/json"
    
    # Accept header for SSE or JSON
    if use_sse:
        headers["Accept"] = "text/event-stream"
    else:
        headers["Accept"] = "application/json"
    
    # Session management
    if session_id:
        headers["Mcp-Session-Id"] = session_id
    
    return headers


# =============================================================================
# Synchronous API Client (using requests)
# =============================================================================

class SyncMCPProxyClient:
    """Synchronous client for interacting with the MCP Proxy API."""
    
    def __init__(self, base_url: str, api_key: Optional[str] = None):
        self.base_url = base_url
        self.api_key = api_key
        self.container_id = None
        self.session_id = None
    
    def create_container(self, tag: str = DEFAULT_TAG) -> str:
        """Create a new container."""
        url = f"{self.base_url}/containers"
        payload = {"tag": tag}
        
        try:
            response = requests.post(
                url,
                headers=get_headers(self.api_key),
                json=payload
            )
            response.raise_for_status()
            container_info = response.json()
            self.container_id = container_info["id"]
            print(f"Container created: {self.container_id}")
            return self.container_id
        except RequestException as e:
            print(f"Error creating container: {e}")
            sys.exit(1)
    
    def destroy_container(self) -> None:
        """Destroy the container."""
        if not self.container_id:
            return
        
        url = f"{self.base_url}/containers/{self.container_id}"
        
        try:
            response = requests.delete(
                url,
                headers=get_headers(self.api_key)
            )
            response.raise_for_status()
            print(f"Container destroyed: {self.container_id}")
            self.container_id = None
            self.session_id = None
        except RequestException as e:
            print(f"Error destroying container: {e}")
    
    def register_mcp_server(self, server_name: str, command: str, args: List[str]) -> None:
        """Register an MCP server in the container."""
        if not self.container_id:
            raise ValueError("No container created")
        
        url = f"{self.base_url}/containers/{self.container_id}/mcp/{server_name}"
        payload = {
            "server_params": {
                "command": command,
                "args": args
            }
        }
        
        try:
            response = requests.put(
                url,
                headers=get_headers(self.api_key),
                json=payload
            )
            response.raise_for_status()
            print(f"MCP server registered: {server_name}")
            print(f"Available tools: {response.json().get('tool_names', [])}")
        except RequestException as e:
            print(f"Error registering MCP server: {e}")
            if hasattr(e, "response") and e.response:
                print(f"Response: {e.response.text}")
    
    def mcp_request(
        self,
        server_name: str,
        request_data: Dict[str, Any],
        use_sse: bool = False
    ) -> Union[Dict[str, Any], List[Dict[str, Any]], None]:
        """Send a request to an MCP server through the proxy."""
        if not self.container_id:
            raise ValueError("No container created")
        
        url = f"{self.base_url}/containers/{self.container_id}/mcp-proxy/{server_name}"
        
        try:
            response = requests.post(
                url,
                headers=get_headers(self.api_key, self.session_id, use_sse),
                json=request_data,
                stream=use_sse
            )
            response.raise_for_status()
            
            # Update session ID if provided
            if "Mcp-Session-Id" in response.headers:
                self.session_id = response.headers["Mcp-Session-Id"]
                print(f"Session ID: {self.session_id}")
            
            if use_sse:
                # Process SSE stream
                for line in response.iter_lines():
                    if line:
                        line = line.decode("utf-8")
                        if line.startswith("data: "):
                            data = line[6:]  # Remove "data: " prefix
                            if data == "[DONE]":
                                print("Stream completed")
                                break
                            try:
                                event_data = json.loads(data)
                                print(f"SSE Event: {json.dumps(event_data, indent=2)}")
                            except json.JSONDecodeError:
                                print(f"Invalid JSON in SSE event: {data}")
                return None
            else:
                # Process JSON response
                result = response.json()
                if isinstance(result, list):
                    # Handle batch response
                    return result
                else:
                    # Handle single response
                    return result
        except RequestException as e:
            print(f"Error sending MCP request: {e}")
            if hasattr(e, "response") and e.response:
                print(f"Response: {e.response.text}")
            return None
    
    def initialize_mcp(self, server_name: str, use_sse: bool = False) -> Dict[str, Any]:
        """Initialize the MCP server."""
        print(f"\n--- Initializing MCP server: {server_name} ---")
        response = self.mcp_request(
            server_name=server_name,
            request_data=INITIALIZE_REQUEST,
            use_sse=use_sse
        )
        if response:
            print(f"Initialization response: {json.dumps(response, indent=2)}")
            return response
        return {}
    
    def list_tools(self, server_name: str, use_sse: bool = False) -> List[Dict[str, Any]]:
        """List available tools in the MCP server."""
        print(f"\n--- Listing tools for MCP server: {server_name} ---")
        response = self.mcp_request(
            server_name=server_name,
            request_data=TOOLS_LIST_REQUEST,
            use_sse=use_sse
        )
        if response:
            tools = response.get("result", {}).get("tools", [])
            print(f"Available tools: {json.dumps(tools, indent=2)}")
            return tools
        return []
    
    def call_tool(
        self,
        server_name: str,
        tool_name: str,
        params: Dict[str, Any],
        use_sse: bool = False
    ) -> Dict[str, Any]:
        """Call a tool in the MCP server."""
        print(f"\n--- Calling tool: {tool_name} ---")
        request = TOOLS_CALL_REQUEST_TEMPLATE.copy()
        request["params"]["tool_name"] = tool_name
        request["params"]["params"] = params
        
        response = self.mcp_request(
            server_name=server_name,
            request_data=request,
            use_sse=use_sse
        )
        if response and not use_sse:
            print(f"Tool response: {json.dumps(response, indent=2)}")
            return response
        return {}


# =============================================================================
# Asynchronous API Client (using aiohttp)
# =============================================================================

class AsyncMCPProxyClient:
    """Asynchronous client for interacting with the MCP Proxy API."""
    
    def __init__(self, base_url: str, api_key: Optional[str] = None):
        self.base_url = base_url
        self.api_key = api_key
        self.container_id = None
        self.session_id = None
        self._session = None
    
    async def __aenter__(self):
        self._session = aiohttp.ClientSession()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.container_id:
            await self.destroy_container()
        if self._session:
            await self._session.close()
    
    async def create_container(self, tag: str = DEFAULT_TAG) -> str:
        """Create a new container."""
        url = f"{self.base_url}/containers"
        payload = {"tag": tag}
        
        try:
            async with self._session.post(
                url,
                headers=get_headers(self.api_key),
                json=payload
            ) as response:
                response.raise_for_status()
                container_info = await response.json()
                self.container_id = container_info["id"]
                print(f"Container created: {self.container_id}")
                return self.container_id
        except aiohttp.ClientError as e:
            print(f"Error creating container: {e}")
            raise
    
    async def destroy_container(self) -> None:
        """Destroy the container."""
        if not self.container_id:
            return
        
        url = f"{self.base_url}/containers/{self.container_id}"
        
        try:
            async with self._session.delete(
                url,
                headers=get_headers(self.api_key)
            ) as response:
                response.raise_for_status()
                print(f"Container destroyed: {self.container_id}")
                self.container_id = None
                self.session_id = None
        except aiohttp.ClientError as e:
            print(f"Error destroying container: {e}")
    
    async def register_mcp_server(self, server_name: str, command: str, args: List[str]) -> None:
        """Register an MCP server in the container."""
        if not self.container_id:
            raise ValueError("No container created")
        
        url = f"{self.base_url}/containers/{self.container_id}/mcp/{server_name}"
        payload = {
            "server_params": {
                "command": command,
                "args": args
            }
        }
        
        try:
            async with self._session.put(
                url,
                headers=get_headers(self.api_key),
                json=payload
            ) as response:
                response.raise_for_status()
                result = await response.json()
                print(f"MCP server registered: {server_name}")
                print(f"Available tools: {result.get('tool_names', [])}")
        except aiohttp.ClientError as e:
            print(f"Error registering MCP server: {e}")
            if hasattr(e, "status") and e.status:
                text = await e.text()
                print(f"Response: {text}")
    
    async def mcp_request(
        self,
        server_name: str,
        request_data: Dict[str, Any],
        use_sse: bool = False
    ) -> Union[Dict[str, Any], List[Dict[str, Any]], None]:
        """Send a request to an MCP server through the proxy."""
        if not self.container_id:
            raise ValueError("No container created")
        
        url = f"{self.base_url}/containers/{self.container_id}/mcp-proxy/{server_name}"
        
        try:
            async with self._session.post(
                url,
                headers=get_headers(self.api_key, self.session_id, use_sse),
                json=request_data
            ) as response:
                response.raise_for_status()
                
                # Update session ID if provided
                if "Mcp-Session-Id" in response.headers:
                    self.session_id = response.headers["Mcp-Session-Id"]
                    print(f"Session ID: {self.session_id}")
                
                if use_sse:
                    # Process SSE stream
                    async for line in response.content:
                        line = line.decode("utf-8").strip()
                        if line.startswith("data: "):
                            data = line[6:]  # Remove "data: " prefix
                            if data == "[DONE]":
                                print("Stream completed")
                                break
                            try:
                                event_data = json.loads(data)
                                print(f"SSE Event: {json.dumps(event_data, indent=2)}")
                            except json.JSONDecodeError:
                                print(f"Invalid JSON in SSE event: {data}")
                    return None
                else:
                    # Process JSON response
                    result = await response.json()
                    if isinstance(result, list):
                        # Handle batch response
                        return result
                    else:
                        # Handle single response
                        return result
        except aiohttp.ClientError as e:
            print(f"Error sending MCP request: {e}")
            if hasattr(e, "status") and e.status:
                text = await e.text()
                print(f"Response: {text}")
            return None
    
    async def initialize_mcp(self, server_name: str, use_sse: bool = False) -> Dict[str, Any]:
        """Initialize the MCP server."""
        print(f"\n--- Initializing MCP server: {server_name} ---")
        response = await self.mcp_request(
            server_name=server_name,
            request_data=INITIALIZE_REQUEST,
            use_sse=use_sse
        )
        if response:
            print(f"Initialization response: {json.dumps(response, indent=2)}")
            return response
        return {}
    
    async def list_tools(self, server_name: str, use_sse: bool = False) -> List[Dict[str, Any]]:
        """List available tools in the MCP server."""
        print(f"\n--- Listing tools for MCP server: {server_name} ---")
        response = await self.mcp_request(
            server_name=server_name,
            request_data=TOOLS_LIST_REQUEST,
            use_sse=use_sse
        )
        if response:
            tools = response.get("result", {}).get("tools", [])
            print(f"Available tools: {json.dumps(tools, indent=2)}")
            return tools
        return []
    
    async def call_tool(
        self,
        server_name: str,
        tool_name: str,
        params: Dict[str, Any],
        use_sse: bool = False
    ) -> Dict[str, Any]:
        """Call a tool in the MCP server."""
        print(f"\n--- Calling tool: {tool_name} ---")
        request = TOOLS_CALL_REQUEST_TEMPLATE.copy()
        request["params"]["tool_name"] = tool_name
        request["params"]["params"] = params
        
        response = await self.mcp_request(
            server_name=server_name,
            request_data=request,
            use_sse=use_sse
        )
        if response and not use_sse:
            print(f"Tool response: {json.dumps(response, indent=2)}")
            return response
        return {}


# =============================================================================
# Synchronous Demo
# =============================================================================

def run_sync_demo():
    """Run the synchronous MCP Proxy demo."""
    print("\n=== Starting Synchronous MCP Proxy Demo ===\n")
    
    client = SyncMCPProxyClient(SERVER_URL, API_KEY)
    
    try:
        # Create container
        client.create_container()
        
        # Register MCP server
        # Using a simple echo MCP server for demo purposes
        client.register_mcp_server(
            server_name="echo",
            command="python3",
            args=["examples/simple_mcp_echo_server.py"]
        )
        
        # Initialize MCP server (JSON response)
        client.initialize_mcp(server_name="echo")
        
        # List tools (JSON response)
        tools = client.list_tools(server_name="echo")
        
        # Call a tool (JSON response)
        if tools and any(tool["name"] == "echo" for tool in tools):
            client.call_tool(
                server_name="echo",
                tool_name="echo",
                params={"message": "Hello from synchronous client!"}
            )
        
        # Initialize MCP server (SSE response)
        client.initialize_mcp(server_name="echo", use_sse=True)
        
        # Call a tool (SSE response)
        if tools and any(tool["name"] == "echo" for tool in tools):
            client.call_tool(
                server_name="echo",
                tool_name="echo",
                params={"message": "Hello from synchronous SSE client!"},
                use_sse=True
            )
        
        # Test error handling with invalid tool
        print("\n--- Testing error handling with invalid tool ---")
        client.call_tool(
            server_name="echo",
            tool_name="non_existent_tool",
            params={}
        )
        
    finally:
        # Clean up
        client.destroy_container()
    
    print("\n=== Synchronous MCP Proxy Demo Completed ===\n")


# =============================================================================
# Asynchronous Demo
# =============================================================================

async def run_async_demo():
    """Run the asynchronous MCP Proxy demo."""
    print("\n=== Starting Asynchronous MCP Proxy Demo ===\n")
    
    async with AsyncMCPProxyClient(SERVER_URL, API_KEY) as client:
        try:
            # Create container
            await client.create_container()
            
            # Register MCP server
            # Using a simple echo MCP server for demo purposes
            await client.register_mcp_server(
                server_name="echo",
                command="python3",
                args=["examples/simple_mcp_echo_server.py"]
            )
            
            # Initialize MCP server (JSON response)
            await client.initialize_mcp(server_name="echo")
            
            # List tools (JSON response)
            tools = await client.list_tools(server_name="echo")
            
            # Call a tool (JSON response)
            if tools and any(tool["name"] == "echo" for tool in tools):
                await client.call_tool(
                    server_name="echo",
                    tool_name="echo",
                    params={"message": "Hello from asynchronous client!"}
                )
            
            # Initialize MCP server (SSE response)
            await client.initialize_mcp(server_name="echo", use_sse=True)
            
            # Call a tool (SSE response)
            if tools and any(tool["name"] == "echo" for tool in tools):
                await client.call_tool(
                    server_name="echo",
                    tool_name="echo",
                    params={"message": "Hello from asynchronous SSE client!"},
                    use_sse=True
                )
            
            # Test error handling with invalid tool
            print("\n--- Testing error handling with invalid tool ---")
            await client.call_tool(
                server_name="echo",
                tool_name="non_existent_tool",
                params={}
            )
            
            # Test batch request
            print("\n--- Testing batch request ---")
            batch_request = [
                INITIALIZE_REQUEST.copy(),
                TOOLS_LIST_REQUEST.copy()
            ]
            batch_request[0]["id"] = 100  # Change ID to avoid conflicts
            batch_request[1]["id"] = 101
            
            response = await client.mcp_request(
                server_name="echo",
                request_data=batch_request
            )
            if response:
                print(f"Batch response: {json.dumps(response, indent=2)}")
            
        except Exception as e:
            print(f"Error in async demo: {e}")
    
    print("\n=== Asynchronous MCP Proxy Demo Completed ===\n")


# =============================================================================
# Main Function
# =============================================================================

async def main():
    """Run both synchronous and asynchronous demos."""
    # Run synchronous demo
    run_sync_demo()
    
    # Wait a bit between demos
    await asyncio.sleep(1)
    
    # Run asynchronous demo
    await run_async_demo()


if __name__ == "__main__":
    asyncio.run(main())
