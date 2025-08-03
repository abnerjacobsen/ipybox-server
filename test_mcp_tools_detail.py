#!/usr/bin/env python3
"""
MCP Tools Detail Test Script

This script demonstrates the enhanced MCP tools endpoint that now returns
detailed tool information including input schemas, not just tool names.

It will:
1. Create a container
2. Register an MCP server using our simple echo server
3. Query the tools endpoint
4. Show the detailed tool information including parameters

Usage:
    python test_mcp_tools_detail.py [--host HOST] [--port PORT] [--api-key KEY]

Requirements:
    - ipybox-server running
    - requests library
    - colorama library (optional, for colored output)
"""

import argparse
import json
import os
import sys
import time
from typing import Dict, Any, Optional, List

import requests
from requests.exceptions import RequestException

# Try to import colorama for colored output
try:
    from colorama import init, Fore, Style
    init()
    
    def green(text):
        return f"{Fore.GREEN}{text}{Style.RESET_ALL}"
    
    def red(text):
        return f"{Fore.RED}{text}{Style.RESET_ALL}"
    
    def yellow(text):
        return f"{Fore.YELLOW}{text}{Style.RESET_ALL}"
    
    def blue(text):
        return f"{Fore.BLUE}{text}{Style.RESET_ALL}"
    
except ImportError:
    # Fallback if colorama is not available
    def green(text):
        return f"✅ {text}"
    
    def red(text):
        return f"❌ {text}"
    
    def yellow(text):
        return f"⚠️ {text}"
    
    def blue(text):
        return f"ℹ️ {text}"

# Default configuration
DEFAULT_HOST = "localhost"
DEFAULT_PORT = 8000
DEFAULT_API_KEY = os.environ.get("IPYBOX_API_KEY", "")
DEFAULT_DOCKER_TAG = "ghcr.io/gradion-ai/ipybox"

class MCPToolsTester:
    """Test the MCP tools endpoint with detailed schema information."""
    
    def __init__(self, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT, api_key: Optional[str] = DEFAULT_API_KEY):
        self.base_url = f"http://{host}:{port}"
        self.api_key = api_key
        self.container_id = None
    
    def get_headers(self):
        """Generate headers for API requests."""
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["X-API-Key"] = self.api_key
        return headers
    
    def create_container(self, tag: str = DEFAULT_DOCKER_TAG) -> str:
        """Create a new container."""
        print(blue("\n📦 Creating container..."))
        
        url = f"{self.base_url}/containers"
        payload = {"tag": tag}
        
        try:
            response = requests.post(
                url,
                headers=self.get_headers(),
                json=payload
            )
            response.raise_for_status()
            container_info = response.json()
            self.container_id = container_info["id"]
            print(green(f"✅ Container created: {self.container_id}"))
            return self.container_id
        except RequestException as e:
            print(red(f"❌ Error creating container: {e}"))
            if hasattr(e, "response") and e.response:
                print(red(f"Response: {e.response.text}"))
            sys.exit(1)
    
    def register_mcp_server(self, server_name: str, command: str, args: List[str]) -> None:
        """Register an MCP server in the container."""
        print(blue(f"\n🔌 Registering MCP server: {server_name}..."))
        
        if not self.container_id:
            print(red("❌ No container created"))
            sys.exit(1)
        
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
                headers=self.get_headers(),
                json=payload
            )
            response.raise_for_status()
            print(green(f"✅ MCP server registered: {server_name}"))
            print(green(f"✅ Available tools: {response.json().get('tool_names', [])}"))
        except RequestException as e:
            print(red(f"❌ Error registering MCP server: {e}"))
            if hasattr(e, "response") and e.response:
                print(red(f"Response: {e.response.text}"))
            sys.exit(1)
    
    def get_mcp_tools(self, server_name: str) -> Dict[str, Any]:
        """Get tools for an MCP server."""
        print(blue(f"\n🔍 Getting tools for MCP server: {server_name}..."))
        
        if not self.container_id:
            print(red("❌ No container created"))
            sys.exit(1)
        
        url = f"{self.base_url}/containers/{self.container_id}/mcp/{server_name}"
        
        try:
            response = requests.get(
                url,
                headers=self.get_headers()
            )
            response.raise_for_status()
            return response.json()
        except RequestException as e:
            print(red(f"❌ Error getting MCP tools: {e}"))
            if hasattr(e, "response") and e.response:
                print(red(f"Response: {e.response.text}"))
            sys.exit(1)
    
    def destroy_container(self) -> None:
        """Destroy the container."""
        if not self.container_id:
            return
        
        print(blue("\n🧹 Cleaning up..."))
        url = f"{self.base_url}/containers/{self.container_id}"
        
        try:
            response = requests.delete(
                url,
                headers=self.get_headers()
            )
            response.raise_for_status()
            print(green(f"✅ Container destroyed: {self.container_id}"))
            self.container_id = None
        except RequestException as e:
            print(red(f"❌ Error destroying container: {e}"))
            if hasattr(e, "response") and e.response:
                print(red(f"Response: {e.response.text}"))
    
    def run_test(self):
        """Run the MCP tools detail test."""
        try:
            # Create container
            self.create_container()
            
            # Register MCP server
            self.register_mcp_server(
                server_name="echo",
                command="python3",
                args=["examples/simple_mcp_echo_server.py"]
            )
            
            # Get MCP tools with detailed info
            tools_info = self.get_mcp_tools(server_name="echo")
            
            # Display the results
            self.display_tools_info(tools_info)
            
        finally:
            # Clean up
            self.destroy_container()
    
    def display_tools_info(self, tools_info: Dict[str, Any]) -> None:
        """Display the tools information in a nice format."""
        print("\n" + "=" * 70)
        print(blue("📋 MCP TOOLS INFORMATION"))
        print("=" * 70)
        
        # Display server name
        print(f"Server: {yellow(tools_info.get('server_name', 'unknown'))}")
        
        # Display tool names (old behavior)
        print("\n" + blue("🔹 LEGACY FORMAT (tool_names only):"))
        tool_names = tools_info.get("tool_names", [])
        if tool_names:
            print(json.dumps(tool_names, indent=2))
        else:
            print(red("No tool names found"))
        
        # Display detailed tools info (new behavior)
        print("\n" + blue("🔹 NEW FORMAT (with detailed schema):"))
        tools = tools_info.get("tools", [])
        if tools:
            print(json.dumps(tools, indent=2))
        else:
            print(red("No detailed tool information found"))
        
        # Show the difference
        print("\n" + "=" * 70)
        print(blue("📊 COMPARISON"))
        print("=" * 70)
        
        print(f"Old behavior: {len(tool_names)} tool names without parameter information")
        print(f"New behavior: {len(tools)} tools with complete schema information")
        
        # Check if we got detailed schema info
        has_schema = any(tool.get("inputSchema") for tool in tools)
        if has_schema:
            print(green("\n✅ SUCCESS: The endpoint now returns detailed tool schemas!"))
        else:
            print(yellow("\n⚠️ NOTE: No detailed schemas found. The endpoint might need further investigation."))
        
        print("\n" + "=" * 70)


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="Test MCP tools endpoint with detailed schema information")
    parser.add_argument("--host", default=DEFAULT_HOST, help=f"Server host (default: {DEFAULT_HOST})")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"Server port (default: {DEFAULT_PORT})")
    parser.add_argument("--api-key", default=DEFAULT_API_KEY, help="API key for authentication")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    
    print("\n" + "=" * 70)
    print(blue("🚀 MCP TOOLS DETAIL TEST"))
    print("=" * 70)
    print(f"Server: {args.host}:{args.port}")
    print(f"API Key: {'Set' if args.api_key else 'Not set'}")
    print("=" * 70 + "\n")
    
    tester = MCPToolsTester(host=args.host, port=args.port, api_key=args.api_key)
    tester.run_test()
