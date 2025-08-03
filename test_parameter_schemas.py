#!/usr/bin/env python3
"""
Parameter Schema Test Script

This script demonstrates that the GET /containers/{id}/mcp/{server} endpoint
now returns detailed parameter schemas instead of just tool names.

It will:
1. Create a container
2. Register two MCP servers (echo and fetch)
3. Call the GET endpoint and show the detailed parameter schemas
4. Compare before/after behavior clearly

Usage:
    python test_parameter_schemas.py [--host HOST] [--port PORT] [--api-key KEY]

Requirements:
    - ipybox-server running
    - requests library
    - colorama library (for colored output)
"""

import argparse
import json
import os
import sys
import time
from typing import Dict, Any, Optional, List

import requests
from requests.exceptions import RequestException

# Import colorama for colored output
from colorama import init, Fore, Style
init(autoreset=True)

# Default configuration
DEFAULT_HOST = "localhost"
DEFAULT_PORT = 8000
DEFAULT_API_KEY = os.environ.get("IPYBOX_API_KEY", "")
DEFAULT_DOCKER_TAG = "ghcr.io/gradion-ai/ipybox"

def green(text):
    return f"{Fore.GREEN}{text}{Style.RESET_ALL}"

def red(text):
    return f"{Fore.RED}{text}{Style.RESET_ALL}"

def yellow(text):
    return f"{Fore.YELLOW}{text}{Style.RESET_ALL}"

def blue(text):
    return f"{Fore.BLUE}{text}{Style.RESET_ALL}"

def cyan(text):
    return f"{Fore.CYAN}{text}{Style.RESET_ALL}"

def magenta(text):
    return f"{Fore.MAGENTA}{text}{Style.RESET_ALL}"

def bold(text):
    return f"{Style.BRIGHT}{text}{Style.RESET_ALL}"

class ParameterSchemaTest:
    """Test the MCP tools endpoint to verify it returns parameter schemas."""
    
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
    
    def display_tools_info(self, server_name: str, tools_info: Dict[str, Any]) -> None:
        """Display the tools information in a nice format."""
        print("\n" + "=" * 70)
        print(bold(blue(f"📋 MCP TOOLS INFORMATION FOR {server_name.upper()}")))
        print("=" * 70)
        
        # Display tool names (old behavior)
        print("\n" + bold(yellow("🔹 BEFORE: LEGACY FORMAT (tool_names only)")))
        tool_names = tools_info.get("tool_names", [])
        if tool_names:
            print(cyan("Tool names: " + ", ".join(tool_names)))
            
            # Show the old format JSON
            old_format = {
                "server_name": server_name,
                "tool_names": tool_names
            }
            print(cyan("JSON response (old format):"))
            print(json.dumps(old_format, indent=2))
        else:
            print(red("No tool names found"))
        
        # Display detailed tools info (new behavior)
        print("\n" + bold(green("🔹 AFTER: ENHANCED FORMAT (with detailed schema)")))
        tools = tools_info.get("tools", [])
        if tools:
            for tool in tools:
                tool_name = tool.get("name", "unknown")
                print(bold(green(f"\n📌 Tool: {tool_name}")))
                
                # Description
                description = tool.get("description", "No description")
                print(cyan(f"Description: {description}"))
                
                # Input Schema
                input_schema = tool.get("inputSchema", {})
                if input_schema:
                    print(green("Input Schema:"))
                    
                    # Properties
                    properties = input_schema.get("properties", {})
                    if properties:
                        print(cyan("  Properties:"))
                        for prop_name, prop_details in properties.items():
                            prop_type = prop_details.get("type", "unknown")
                            prop_desc = prop_details.get("description", "No description")
                            print(f"    {magenta(prop_name)}: {yellow(prop_type)} - {prop_desc}")
                    
                    # Required fields
                    required = input_schema.get("required", [])
                    if required:
                        print(cyan(f"  Required fields: {', '.join(required)}"))
                else:
                    print(yellow("  No input schema defined"))
                
                # Returns/Output Schema
                returns = tool.get("returns", {})
                if returns:
                    print(green("Returns:"))
                    returns_type = returns.get("type", "unknown")
                    returns_desc = returns.get("description", "No description")
                    print(f"  {yellow(returns_type)} - {returns_desc}")
            
            # Show the full JSON for developers
            print(bold(green("\n📝 Complete JSON Response:")))
            print(json.dumps(tools_info, indent=2))
        else:
            print(red("No detailed tool information found"))
    
    def run_test(self):
        """Run the parameter schema test."""
        try:
            # Create container
            self.create_container()
            
            # Register MCP echo server (simple parameters)
            self.register_mcp_server(
                server_name="echo",
                command="python3",
                args=["examples/simple_mcp_echo_server.py"]
            )
            
            # Register MCP fetch server (complex parameters)
            self.register_mcp_server(
                server_name="fetchurl",
                command="python3",
                args=["examples/simple_mcp_fetch_server.py"]
            )
            
            # Get MCP tools with detailed info for echo server
            echo_tools_info = self.get_mcp_tools(server_name="echo")
            
            # Get MCP tools with detailed info for fetch server
            fetch_tools_info = self.get_mcp_tools(server_name="fetchurl")
            
            # Display the results
            self.display_tools_info("echo", echo_tools_info)
            self.display_tools_info("fetchurl", fetch_tools_info)
            
            # Show summary
            print("\n" + "=" * 70)
            print(bold(blue("📊 PARAMETER SCHEMA TEST SUMMARY")))
            print("=" * 70)
            
            # Check if we got detailed schema info for echo
            echo_has_schema = any(tool.get("inputSchema", {}).get("properties") for tool in echo_tools_info.get("tools", []))
            
            # Check if we got detailed schema info for fetch
            fetch_has_schema = any(tool.get("inputSchema", {}).get("properties") for tool in fetch_tools_info.get("tools", []))
            
            if echo_has_schema and fetch_has_schema:
                print(bold(green("\n✅ SUCCESS: The endpoint now returns detailed tool schemas!")))
                print(green("✅ Both echo and fetch servers return complete parameter information"))
                print(green("✅ The schema includes property types, descriptions, and required fields"))
            else:
                print(bold(yellow("\n⚠️ PARTIAL SUCCESS:")))
                if echo_has_schema:
                    print(green("✅ Echo server returns parameter schemas"))
                else:
                    print(red("❌ Echo server does not return parameter schemas"))
                
                if fetch_has_schema:
                    print(green("✅ Fetch server returns parameter schemas"))
                else:
                    print(red("❌ Fetch server does not return parameter schemas"))
            
            print("\n" + "=" * 70)
            
        finally:
            # Clean up
            self.destroy_container()


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
    print(bold(blue("🚀 MCP PARAMETER SCHEMA TEST")))
    print("=" * 70)
    print(f"Server: {args.host}:{args.port}")
    print(f"API Key: {'Set' if args.api_key else 'Not set'}")
    print("=" * 70 + "\n")
    
    tester = ParameterSchemaTest(host=args.host, port=args.port, api_key=args.api_key)
    tester.run_test()
