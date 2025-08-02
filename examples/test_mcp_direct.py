#!/usr/bin/env python3
"""
Direct MCP Proxy Test

This script tests the MCP proxy functionality directly without going through the web server.
It creates a mock container manager, initializes the MCP proxy, and tests sending
JSON-RPC messages to a simple MCP echo server.

This is useful for debugging MCP proxy issues in isolation from the web server.
"""

import asyncio
import json
import logging
import os
import sys
import time
from typing import Dict, Any, Optional

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("test_mcp_direct")

# Add the project root to the Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Import MCP proxy
from ipybox.mcp_proxy import create_mcp_proxy, MCPSession

# JSON-RPC request templates
INITIALIZE_REQUEST = {
    "jsonrpc": "2.0",
    "method": "initialize",
    "params": {
        "protocol_version": "2025-03-26",
        "client_info": {
            "name": "test_mcp_direct",
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
            "message": "Hello, MCP!"
        }
    },
    "id": 3
}

# Mock container manager
class MockContainerManager:
    """Mock container manager for testing MCP proxy"""
    
    async def get_container(self, container_id: str):
        """Mock method to get a container"""
        return {"id": container_id}


class MCPProxyTester:
    """Test the MCP proxy functionality directly"""
    
    def __init__(self, echo_server_path: str = "examples/simple_mcp_echo_server.py"):
        self.container_manager = MockContainerManager()
        self.proxy = None
        self.echo_server_path = echo_server_path
        self.container_id = "test-container-001"
        self.server_name = "echo"
        self.session_id = None
        self.session = None
    
    async def setup(self):
        """Set up the MCP proxy"""
        logger.info("Setting up MCP proxy")
        self.proxy = create_mcp_proxy(
            container_manager=self.container_manager,
            session_timeout=60,  # Short timeout for testing
            cleanup_interval=10   # Short cleanup interval for testing
        )
        await self.proxy.start()
        logger.info("MCP proxy started")
    
    async def create_session(self):
        """Create an MCP session"""
        logger.info("Creating MCP session")
        
        # Use the simple echo server for testing
        command = sys.executable  # Current Python interpreter
        args = [self.echo_server_path]
        
        try:
            self.session_id, self.session = await self.proxy.get_or_create_session(
                container_id=self.container_id,
                server_name=self.server_name,
                command=command,
                args=args
            )
            logger.info(f"Created MCP session: {self.session_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to create MCP session: {e}")
            return False
    
    async def test_initialize(self):
        """Test initializing the MCP server"""
        logger.info("Testing initialize")
        try:
            await self.session.send_message(INITIALIZE_REQUEST)
            response = await self.session.receive_message(timeout=10.0)
            logger.info(f"Initialize response: {json.dumps(response, indent=2)}")
            
            # Verify response
            assert response.get("jsonrpc") == "2.0", "Invalid JSON-RPC version"
            assert response.get("id") == 1, "Invalid response ID"
            assert "result" in response, "Missing result field"
            assert "protocol_version" in response["result"], "Missing protocol version"
            assert "capabilities" in response["result"], "Missing capabilities"
            
            logger.info("Initialize test passed")
            return True
        except Exception as e:
            logger.error(f"Initialize test failed: {e}")
            return False
    
    async def test_tools_list(self):
        """Test listing tools"""
        logger.info("Testing tools/list")
        try:
            await self.session.send_message(TOOLS_LIST_REQUEST)
            response = await self.session.receive_message(timeout=10.0)
            logger.info(f"Tools list response: {json.dumps(response, indent=2)}")
            
            # Verify response
            assert response.get("jsonrpc") == "2.0", "Invalid JSON-RPC version"
            assert response.get("id") == 2, "Invalid response ID"
            assert "result" in response, "Missing result field"
            assert "tools" in response["result"], "Missing tools field"
            assert len(response["result"]["tools"]) > 0, "No tools returned"
            
            # Verify echo tool exists
            tools = response["result"]["tools"]
            echo_tools = [t for t in tools if t.get("name") == "echo"]
            assert len(echo_tools) > 0, "Echo tool not found"
            
            logger.info("Tools list test passed")
            return True
        except Exception as e:
            logger.error(f"Tools list test failed: {e}")
            return False
    
    async def test_echo_tool(self):
        """Test calling the echo tool"""
        logger.info("Testing echo tool")
        try:
            await self.session.send_message(ECHO_TOOL_REQUEST)
            response = await self.session.receive_message(timeout=10.0)
            logger.info(f"Echo tool response: {json.dumps(response, indent=2)}")
            
            # Verify response
            assert response.get("jsonrpc") == "2.0", "Invalid JSON-RPC version"
            assert response.get("id") == 3, "Invalid response ID"
            assert "result" in response, "Missing result field"
            assert response["result"] == "Hello, MCP!", "Incorrect echo response"
            
            logger.info("Echo tool test passed")
            return True
        except Exception as e:
            logger.error(f"Echo tool test failed: {e}")
            return False
    
    async def teardown(self):
        """Clean up resources"""
        logger.info("Tearing down")
        
        if self.session:
            try:
                await self.session.stop()
                logger.info("MCP session stopped")
            except Exception as e:
                logger.error(f"Error stopping MCP session: {e}")
        
        if self.proxy:
            try:
                await self.proxy.stop()
                logger.info("MCP proxy stopped")
            except Exception as e:
                logger.error(f"Error stopping MCP proxy: {e}")
    
    async def run_tests(self):
        """Run all tests"""
        try:
            # Setup
            await self.setup()
            
            # Create session
            if not await self.create_session():
                logger.error("Failed to create MCP session, aborting tests")
                return False
            
            # Run tests
            initialize_passed = await self.test_initialize()
            if not initialize_passed:
                logger.error("Initialize test failed, aborting remaining tests")
                return False
            
            tools_list_passed = await self.test_tools_list()
            if not tools_list_passed:
                logger.error("Tools list test failed, aborting remaining tests")
                return False
            
            echo_passed = await self.test_echo_tool()
            
            # Overall result
            all_passed = initialize_passed and tools_list_passed and echo_passed
            if all_passed:
                logger.info("All tests passed!")
            else:
                logger.error("Some tests failed")
            
            return all_passed
        finally:
            # Always clean up
            await self.teardown()


async def main():
    """Main entry point"""
    logger.info("Starting direct MCP proxy test")
    
    tester = MCPProxyTester()
    success = await tester.run_tests()
    
    if success:
        logger.info("All tests completed successfully")
        return 0
    else:
        logger.error("Tests failed")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
