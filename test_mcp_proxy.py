#!/usr/bin/env python3
"""
MCP Proxy Quick Test

This script provides a simple way to test if the MCP proxy functionality
is working correctly without needing to start the full web server.

It tests:
1. Basic MCP proxy initialization
2. Session creation with a simple echo server
3. JSON-RPC 2.0 communication (initialize, tools/list, tools/call)
4. Clean session termination

Run this script directly to verify your MCP proxy implementation:
    python test_mcp_proxy.py
"""

import asyncio
import json
import logging
import os
import sys
import time
from typing import Dict, Any, Optional, List, Tuple

# Configure colorful output if available
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

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("mcp_proxy_test")

# Import MCP proxy (with helpful error handling)
try:
    from ipybox.mcp_proxy import create_mcp_proxy, MCPSession
except ImportError as e:
    print(red(f"Error importing MCP proxy: {e}"))
    print(yellow("Make sure you're running this script from the project root directory."))
    print(yellow("Try: cd /path/to/ipybox-server && python test_mcp_proxy.py"))
    sys.exit(1)

# JSON-RPC request templates
INITIALIZE_REQUEST = {
    "jsonrpc": "2.0",
    "method": "initialize",
    "params": {
        "protocol_version": "2025-03-26",
        "client_info": {
            "name": "mcp_proxy_test",
            "version": "1.0.0"
        },
        "capabilities": {
            "tools": True,
            "resources": False,
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

ECHO_TOOL_REQUEST = {
    "jsonrpc": "2.0",
    "method": "tools/call",
    "params": {
        "tool_name": "echo",
        "params": {
            "message": "Hello from MCP Proxy Test!"
        }
    },
    "id": 3
}

# Mock container manager (simplified for testing)
class MockContainerManager:
    """Mock container manager for testing MCP proxy"""
    
    async def get_container(self, container_id: str):
        """Mock method to get a container"""
        return {"id": container_id}


class MCPProxyTester:
    """User-friendly MCP proxy tester"""
    
    def __init__(self):
        self.container_manager = MockContainerManager()
        self.proxy = None
        self.echo_server_path = "examples/simple_mcp_echo_server.py"
        self.container_id = "test-container-001"
        self.server_name = "echo"
        self.session_id = None
        self.session = None
        self.results = {
            "proxy_creation": False,
            "session_creation": False,
            "initialize": False,
            "tools_list": False,
            "echo_tool": False,
            "cleanup": False
        }
    
    async def test_proxy_creation(self):
        """Test creating the MCP proxy"""
        print(blue("📋 Step 1/5: Creating MCP proxy..."))
        try:
            self.proxy = create_mcp_proxy(
                container_manager=self.container_manager,
                session_timeout=60,
                cleanup_interval=10
            )
            await self.proxy.start()
            self.results["proxy_creation"] = True
            print(green("✅ MCP proxy created and started successfully"))
            return True
        except Exception as e:
            print(red(f"❌ Failed to create MCP proxy: {e}"))
            return False
    
    async def test_session_creation(self):
        """Test creating an MCP session with the echo server"""
        print(blue("\n📋 Step 2/5: Creating MCP session with echo server..."))
        
        # Check if echo server exists
        if not os.path.exists(self.echo_server_path):
            print(red(f"❌ Echo server not found at {self.echo_server_path}"))
            print(yellow("Make sure you're running this script from the project root directory"))
            print(yellow("and that examples/simple_mcp_echo_server.py exists."))
            return False
        
        # Create session
        try:
            command = sys.executable  # Current Python interpreter
            args = [self.echo_server_path]
            
            self.session_id, self.session = await self.proxy.get_or_create_session(
                container_id=self.container_id,
                server_name=self.server_name,
                command=command,
                args=args
            )
            self.results["session_creation"] = True
            print(green(f"✅ MCP session created successfully: {self.session_id}"))
            return True
        except Exception as e:
            print(red(f"❌ Failed to create MCP session: {e}"))
            return False
    
    async def test_initialize(self):
        """Test initializing the MCP server"""
        print(blue("\n📋 Step 3/5: Testing MCP initialize..."))
        try:
            await self.session.send_message(INITIALIZE_REQUEST)
            response = await self.session.receive_message(timeout=10.0)
            
            # Print response in a nice format
            print(blue("Response from MCP server:"))
            print(json.dumps(response, indent=2))
            
            # Verify response
            if (response.get("jsonrpc") == "2.0" and
                response.get("id") == 1 and
                "result" in response and
                "protocol_version" in response["result"]):
                self.results["initialize"] = True
                print(green("✅ Initialize successful"))
                return True
            else:
                print(red("❌ Invalid initialize response"))
                return False
        except Exception as e:
            print(red(f"❌ Initialize failed: {e}"))
            return False
    
    async def test_tools_list(self):
        """Test listing tools"""
        print(blue("\n📋 Step 4/5: Testing MCP tools/list..."))
        try:
            await self.session.send_message(TOOLS_LIST_REQUEST)
            response = await self.session.receive_message(timeout=10.0)
            
            # Print response in a nice format
            print(blue("Response from MCP server:"))
            print(json.dumps(response, indent=2))
            
            # Verify response
            if (response.get("jsonrpc") == "2.0" and
                response.get("id") == 2 and
                "result" in response and
                "tools" in response["result"]):
                
                tools = response["result"]["tools"]
                if tools and any(t.get("name") == "echo" for t in tools):
                    self.results["tools_list"] = True
                    print(green(f"✅ Found {len(tools)} tools including 'echo'"))
                    return True
                else:
                    print(red("❌ Echo tool not found in tools list"))
                    return False
            else:
                print(red("❌ Invalid tools/list response"))
                return False
        except Exception as e:
            print(red(f"❌ Tools list failed: {e}"))
            return False
    
    async def test_echo_tool(self):
        """Test calling the echo tool"""
        print(blue("\n📋 Step 5/5: Testing MCP tools/call with echo..."))
        try:
            await self.session.send_message(ECHO_TOOL_REQUEST)
            response = await self.session.receive_message(timeout=10.0)
            
            # Print response in a nice format
            print(blue("Response from MCP server:"))
            print(json.dumps(response, indent=2))
            
            # Verify response
            if (response.get("jsonrpc") == "2.0" and
                response.get("id") == 3 and
                "result" in response and
                response["result"] == "Hello from MCP Proxy Test!"):
                self.results["echo_tool"] = True
                print(green("✅ Echo tool call successful"))
                return True
            else:
                print(red("❌ Invalid echo tool response"))
                return False
        except Exception as e:
            print(red(f"❌ Echo tool call failed: {e}"))
            return False
    
    async def cleanup(self):
        """Clean up resources"""
        print(blue("\n📋 Cleaning up..."))
        
        success = True
        
        if self.session:
            try:
                await self.session.stop()
                print(green("✅ MCP session stopped"))
            except Exception as e:
                print(red(f"❌ Error stopping MCP session: {e}"))
                success = False
        
        if self.proxy:
            try:
                await self.proxy.stop()
                print(green("✅ MCP proxy stopped"))
            except Exception as e:
                print(red(f"❌ Error stopping MCP proxy: {e}"))
                success = False
        
        self.results["cleanup"] = success
        return success
    
    def print_summary(self):
        """Print a summary of the test results"""
        print("\n" + "=" * 60)
        print(blue("📊 MCP PROXY TEST SUMMARY"))
        print("=" * 60)
        
        all_passed = True
        for test, result in self.results.items():
            status = green("PASS") if result else red("FAIL")
            print(f"{test.replace('_', ' ').title()}: {status}")
            if not result:
                all_passed = False
        
        print("=" * 60)
        if all_passed:
            print(green("🎉 ALL TESTS PASSED! The MCP proxy is working correctly."))
            print(blue("\nNext steps:"))
            print("1. Start the full server with: python run_server.py")
            print("2. Try the complete demo: python examples/mcp_proxy_demo.py")
            print("3. Integrate with your own MCP clients using the API")
        else:
            print(red("❌ Some tests failed. Please check the errors above."))
            print(yellow("\nTroubleshooting tips:"))
            print("1. Make sure all dependencies are installed")
            print("2. Check that the echo server exists at examples/simple_mcp_echo_server.py")
            print("3. Look for detailed errors in the logs")
            print("4. Run with DEBUG logging: export LOGLEVEL=DEBUG && python test_mcp_proxy.py")
        
        return all_passed
    
    async def run_tests(self):
        """Run all tests in sequence"""
        try:
            # Step 1: Create proxy
            if not await self.test_proxy_creation():
                return False
            
            # Step 2: Create session
            if not await self.test_session_creation():
                return False
            
            # Step 3: Initialize
            if not await self.test_initialize():
                return False
            
            # Step 4: List tools
            if not await self.test_tools_list():
                return False
            
            # Step 5: Call echo tool
            if not await self.test_echo_tool():
                return False
            
            return True
        except Exception as e:
            print(red(f"Unexpected error during tests: {e}"))
            return False
        finally:
            # Always clean up
            await self.cleanup()


async def main():
    """Main entry point"""
    print("\n" + "=" * 60)
    print(blue("🚀 MCP PROXY TEST"))
    print("=" * 60)
    print("This script tests if the MCP proxy is working correctly.")
    print("It will create a mock session and test basic MCP operations.")
    print("=" * 60 + "\n")
    
    tester = MCPProxyTester()
    
    try:
        await tester.run_tests()
    except KeyboardInterrupt:
        print(yellow("\n\nTest interrupted by user."))
    except Exception as e:
        print(red(f"\nUnexpected error: {e}"))
    finally:
        tester.print_summary()


if __name__ == "__main__":
    # Set log level from environment variable or default to INFO
    log_level = os.environ.get("LOGLEVEL", "INFO").upper()
    logging.getLogger().setLevel(log_level)
    
    # Run the tests
    asyncio.run(main())
