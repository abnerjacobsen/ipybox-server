#!/usr/bin/env python3
"""
Simple MCP Fetch Server

This is a minimal implementation of an MCP server that communicates over stdio
and implements a simple fetch tool. It follows the JSON-RPC 2.0 protocol and
is designed for testing the MCP proxy functionality.

The fetch tool simulates fetching URLs. If the requests library is available,
it will actually fetch the URL. Otherwise, it will return mock data.
"""

import json
import sys
import logging
import traceback
import time
from typing import Dict, Any, List, Optional
from urllib.parse import urlparse

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    filename="mcp_fetch_server.log",  # Log to file for debugging
    filemode="a",
)
logger = logging.getLogger("mcp_fetch_server")

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

# Try to import requests for actual URL fetching
try:
    import requests
    HAS_REQUESTS = True
    logger.info("Requests library available, will fetch real URLs")
except ImportError:
    HAS_REQUESTS = False
    logger.info("Requests library not available, will use mock data")

# Available tools
TOOLS = [
    {
        "name": "fetch",
        "description": "Fetches content from a URL",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "The URL to fetch content from"
                },
                "timeout": {
                    "type": "number",
                    "description": "Timeout in seconds",
                    "default": 10
                },
                "headers": {
                    "type": "object",
                    "description": "Optional HTTP headers to include in the request",
                    "additionalProperties": {
                        "type": "string"
                    }
                }
            },
            "required": ["url"]
        },
        "returns": {
            "type": "object",
            "description": "The fetched content and metadata",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "The content of the URL"
                },
                "status_code": {
                    "type": "integer",
                    "description": "HTTP status code"
                },
                "headers": {
                    "type": "object",
                    "description": "Response headers"
                },
                "url": {
                    "type": "string",
                    "description": "Final URL after redirects"
                },
                "elapsed": {
                    "type": "number",
                    "description": "Time taken to fetch the URL in seconds"
                }
            }
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

def fetch_url_with_requests(url: str, timeout: float = 10, headers: Dict[str, str] = None) -> Dict[str, Any]:
    """Fetch a URL using the requests library."""
    try:
        start_time = time.time()
        response = requests.get(url, timeout=timeout, headers=headers or {})
        elapsed = time.time() - start_time
        
        # Limit content size to avoid huge responses
        content = response.text[:10000]
        if len(response.text) > 10000:
            content += "... [content truncated]"
        
        return {
            "content": content,
            "status_code": response.status_code,
            "headers": dict(response.headers),
            "url": response.url,
            "elapsed": elapsed
        }
    except requests.RequestException as e:
        logger.error(f"Error fetching URL {url}: {str(e)}")
        raise Exception(f"Error fetching URL: {str(e)}")

def fetch_url_mock(url: str, timeout: float = 10, headers: Dict[str, str] = None) -> Dict[str, Any]:
    """Mock URL fetching when requests library is not available."""
    try:
        # Parse the URL to validate it
        parsed_url = urlparse(url)
        if not parsed_url.scheme or not parsed_url.netloc:
            raise ValueError("Invalid URL format")
        
        # Simulate network delay
        time.sleep(min(timeout / 10, 0.5))
        
        # Return mock data
        return {
            "content": f"<html><body><h1>Mock content for {url}</h1><p>This is simulated content because the requests library is not available.</p></body></html>",
            "status_code": 200,
            "headers": {
                "Content-Type": "text/html",
                "Server": "MCP-Mock-Server/1.0",
                "Date": time.strftime("%a, %d %b %Y %H:%M:%S GMT", time.gmtime())
            },
            "url": url,
            "elapsed": min(timeout / 10, 0.5)
        }
    except Exception as e:
        logger.error(f"Error in mock fetch for URL {url}: {str(e)}")
        raise Exception(f"Error fetching URL: {str(e)}")

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
    if tool_name != "fetch":
        return create_error_response(
            ERROR_METHOD_NOT_FOUND,
            f"Tool '{tool_name}' not found",
            request_id
        )
    
    # Check required parameters
    url = tool_params.get("url")
    if url is None:
        return create_error_response(
            ERROR_INVALID_PARAMS,
            "Missing required parameter 'url'",
            request_id
        )
    
    # Get optional parameters
    timeout = tool_params.get("timeout", 10)
    headers = tool_params.get("headers", {})
    
    # Execute the fetch tool
    try:
        if HAS_REQUESTS:
            result = fetch_url_with_requests(url, timeout, headers)
        else:
            result = fetch_url_mock(url, timeout, headers)
        
        logger.info(f"Fetch tool executed successfully for URL: '{url}'")
        return create_success_response(result, request_id)
    except Exception as e:
        logger.error(f"Error executing fetch tool: {str(e)}")
        return create_error_response(
            ERROR_INTERNAL_ERROR,
            f"Error executing fetch tool: {str(e)}",
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
    """Main entry point for the MCP fetch server."""
    logger.info("Starting MCP fetch server")
    
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
        logger.info("MCP fetch server stopped")

if __name__ == "__main__":
    main()
