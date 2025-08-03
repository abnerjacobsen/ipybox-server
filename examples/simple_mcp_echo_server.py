#!/usr/bin/env python3
"""
Simple MCP Echo Server

This is a minimal implementation of an MCP server that communicates over stdio
and implements a simple echo tool. It follows the JSON-RPC 2.0 protocol and
is designed for testing the MCP proxy functionality.
"""

import json
import sys
import logging
import traceback
from typing import Dict, Any, List, Optional

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    filename="mcp_echo_server.log",  # Log to file for debugging
    filemode="a",
)
logger = logging.getLogger("mcp_echo_server")

# Add a stderr handler for immediate feedback
stderr_handler = logging.StreamHandler(sys.stderr)
stderr_handler.setLevel(logging.INFO)
stderr_formatter = logging.Formatter("%(levelname)s: %(message)s")
stderr_handler.setFormatter(stderr_formatter)
logger.addHandler(stderr_handler)

# JSON-RPC 2.0 error codes
ERROR_PARSE_ERROR = -32700
ERROR_INVALID_REQUEST = -32600
ERROR_METHOD_NOT_FOUND = -32601
ERROR_INVALID_PARAMS = -32602
ERROR_INTERNAL_ERROR = -32603

# Server state
server_state = {
    "initialized": False,
    "protocol_version": None,
    "capabilities": {
        "tools": True,
        "prompts": False,
        "completions": False,
        "sampling": False
    }
}

# Available tools
TOOLS = [
    {
        "name": "echo",
        "description": "Echoes back the input message",
        "parameters": {
            "type": "object",
            "properties": {
                "message": {
                    "type": "string",
                    "description": "The message to echo back"
                }
            },
            "required": ["message"]
        },
        "returns": {
            "type": "string",
            "description": "The echoed message"
        }
    }
]

def write_response(response: Dict[str, Any]) -> None:
    """Write a JSON-RPC response to stdout."""
    try:
        response_str = json.dumps(response)
        logger.debug(f"Sending response: {response_str}")
        sys.stdout.write(response_str + "\n")
        sys.stdout.flush()
    except Exception as e:
        logger.error(f"Error writing response: {str(e)}")

def create_error_response(code: int, message: str, request_id: Any) -> Dict[str, Any]:
    """Create a JSON-RPC error response."""
    return {
        "jsonrpc": "2.0",
        "error": {
            "code": code,
            "message": message
        },
        "id": request_id
    }

def create_success_response(result: Any, request_id: Any) -> Dict[str, Any]:
    """Create a JSON-RPC success response."""
    return {
        "jsonrpc": "2.0",
        "result": result,
        "id": request_id
    }

def handle_initialize(params: Dict[str, Any], request_id: Any) -> Dict[str, Any]:
    """Handle the initialize method."""
    logger.info("Handling initialize request")
    
    # Update server state
    server_state["initialized"] = True
    server_state["protocol_version"] = params.get("protocol_version", "2025-03-26")
    
    # Return server capabilities
    result = {
        "protocol_version": server_state["protocol_version"],
        "capabilities": server_state["capabilities"]
    }
    
    return create_success_response(result, request_id)

def handle_tools_list(params: Dict[str, Any], request_id: Any) -> Dict[str, Any]:
    """Handle the tools/list method."""
    logger.info("Handling tools/list request")
    
    if not server_state["initialized"]:
        return create_error_response(
            ERROR_INVALID_REQUEST,
            "Server not initialized",
            request_id
        )
    
    result = {
        "tools": TOOLS
    }
    
    return create_success_response(result, request_id)

def handle_tools_call(params: Dict[str, Any], request_id: Any) -> Dict[str, Any]:
    """Handle the tools/call method."""
    tool_name = params.get("tool_name")
    tool_params = params.get("params", {})
    
    logger.info(f"Handling tools/call request for tool '{tool_name}'")
    
    if not server_state["initialized"]:
        return create_error_response(
            ERROR_INVALID_REQUEST,
            "Server not initialized",
            request_id
        )
    
    # Check if tool exists
    if tool_name != "echo":
        return create_error_response(
            ERROR_METHOD_NOT_FOUND,
            f"Tool '{tool_name}' not found",
            request_id
        )
    
    # Check required parameters
    message = tool_params.get("message")
    if message is None:
        return create_error_response(
            ERROR_INVALID_PARAMS,
            "Missing required parameter 'message'",
            request_id
        )
    
    # Execute the echo tool
    try:
        result = message  # Simply echo back the message
        logger.info(f"Echo tool executed successfully: '{message}'")
        return create_success_response(result, request_id)
    except Exception as e:
        logger.error(f"Error executing echo tool: {str(e)}")
        return create_error_response(
            ERROR_INTERNAL_ERROR,
            f"Error executing echo tool: {str(e)}",
            request_id
        )

def handle_request(request_str: str) -> None:
    """Parse and handle a JSON-RPC request."""
    try:
        # Parse the request
        request = json.loads(request_str)
        logger.debug(f"Received request: {request}")
        
        # Validate JSON-RPC 2.0 request
        if not isinstance(request, dict) or request.get("jsonrpc") != "2.0":
            write_response(create_error_response(
                ERROR_INVALID_REQUEST,
                "Invalid JSON-RPC 2.0 request",
                None
            ))
            return
        
        # Extract request components
        method = request.get("method")
        params = request.get("params", {})
        request_id = request.get("id")
        
        # Check if it's a notification (no id)
        is_notification = request_id is None
        
        # Handle different methods
        if method == "initialize":
            response = handle_initialize(params, request_id)
        elif method == "tools/list":
            response = handle_tools_list(params, request_id)
        elif method == "tools/call":
            response = handle_tools_call(params, request_id)
        else:
            response = create_error_response(
                ERROR_METHOD_NOT_FOUND,
                f"Method '{method}' not found",
                request_id
            )
        
        # Send response (unless it's a notification)
        if not is_notification:
            write_response(response)
            
    except json.JSONDecodeError:
        logger.error(f"Failed to parse JSON request: {request_str}")
        write_response(create_error_response(
            ERROR_PARSE_ERROR,
            "Parse error",
            None
        ))
    except Exception as e:
        logger.error(f"Error handling request: {str(e)}")
        logger.error(traceback.format_exc())
        write_response(create_error_response(
            ERROR_INTERNAL_ERROR,
            f"Internal error: {str(e)}",
            None
        ))

def main():
    """Main entry point for the MCP echo server."""
    logger.info("Starting MCP echo server")
    
    try:
        # Main loop: read from stdin, process, write to stdout
        for line in sys.stdin:
            line = line.strip()
            if line:
                handle_request(line)
    except KeyboardInterrupt:
        logger.info("Server stopped by user")
    except Exception as e:
        logger.error(f"Unhandled exception: {str(e)}")
        logger.error(traceback.format_exc())
    finally:
        logger.info("MCP echo server stopped")

if __name__ == "__main__":
    main()
