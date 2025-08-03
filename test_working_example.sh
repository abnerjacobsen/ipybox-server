#!/bin/bash
# ===================================================================
# MCP Proxy Working Example
# ===================================================================
# This script demonstrates the complete MCP proxy functionality
# using local Python-based MCP servers instead of uvx.
# 
# It shows:
# 1. Container creation and basic execution
# 2. MCP server registration with Python-based servers
# 3. Listing tools with detailed schema information
# 4. Executing MCP tools via both legacy and proxy endpoints
# 5. Proper cleanup
# ===================================================================

# Text formatting
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# ===================================================================
# Configuration
# ===================================================================
API="http://localhost:8000"
KEY=""  # Set your API key here or leave empty if auth is disabled
TAG="ghcr.io/gradion-ai/ipybox"  # Docker image tag

# Add API key header if set
HDR=""
if [ -n "$KEY" ]; then
  HDR="-H X-API-Key:$KEY"
fi

# ===================================================================
# Helper Functions
# ===================================================================

headline() {
  echo -e "\n${BLUE}=== $1 ===${NC}"
}

success() {
  echo -e "${GREEN}✓ $1${NC}"
}

info() {
  echo -e "${YELLOW}→ $1${NC}"
}

error() {
  echo -e "${RED}✗ $1${NC}"
  exit 1
}

# ===================================================================
# Main Script
# ===================================================================
headline "Starting MCP Proxy Demo"

# Check if jq is installed
if ! command -v jq &> /dev/null; then
  error "jq is required but not installed. Please install jq first."
fi

# Create container
headline "Creating Container"
info "Creating new container with tag: $TAG"

CONTAINER_RESPONSE=$(curl -s -X POST $API/containers $HDR \
  -H "Content-Type:application/json" \
  -d "{\"tag\":\"$TAG\"}")

if [ $? -ne 0 ]; then
  error "Failed to create container"
fi

CID=$(echo $CONTAINER_RESPONSE | jq -r .id)
if [ -z "$CID" ] || [ "$CID" == "null" ]; then
  error "Failed to get container ID from response"
fi

success "Container created with ID: $CID"

# Basic code execution test
headline "Testing Basic Code Execution"
info "Executing simple Python code: print(2+2)"

RESULT=$(curl -s -X POST $API/containers/$CID/execute $HDR \
  -H "Content-Type:application/json" \
  -d '{"code":"print(2+2)"}' | jq -r .text)

if [ "$RESULT" == "4" ]; then
  success "Code execution successful: 2+2 = $RESULT"
else
  error "Code execution failed. Expected 4, got: $RESULT"
fi

# Register MCP echo server
headline "Registering MCP Echo Server"
info "Using Python-based echo server"

ECHO_RESPONSE=$(curl -s -X PUT $API/containers/$CID/mcp/echo $HDR \
  -H "Content-Type:application/json" \
  -d '{"server_params":{"command":"python3","args":["examples/simple_mcp_echo_server.py"]}}')

ECHO_TOOLS=$(echo $ECHO_RESPONSE | jq -r '.tool_names | join(", ")')
success "Echo server registered with tools: $ECHO_TOOLS"

# Register MCP fetch server
headline "Registering MCP Fetch Server"
info "Using Python-based fetch server"

FETCH_RESPONSE=$(curl -s -X PUT $API/containers/$CID/mcp/fetchurl $HDR \
  -H "Content-Type:application/json" \
  -d '{"server_params":{"command":"python3","args":["examples/simple_mcp_fetch_server.py"]}}')

FETCH_TOOLS=$(echo $FETCH_RESPONSE | jq -r '.tool_names | join(", ")')
success "Fetch server registered with tools: $FETCH_TOOLS"

# List tools with detailed information
headline "Listing MCP Tools with Detailed Schema"
info "Echo server tools:"
curl -s $API/containers/$CID/mcp/echo $HDR | jq '.'

info "Fetch server tools:"
curl -s $API/containers/$CID/mcp/fetchurl $HDR | jq '.'

# Call echo tool using legacy endpoint
headline "Calling Echo Tool (Legacy Endpoint)"
info "Sending message: 'Hello from MCP!'"

ECHO_RESULT=$(curl -s -X POST $API/containers/$CID/mcp/echo/echo $HDR \
  -H "Content-Type:application/json" \
  -d '{"params":{"message":"Hello from MCP!"}, "timeout": 5}' | jq -r .result)

success "Echo response: $ECHO_RESULT"

# Call fetch tool using legacy endpoint
headline "Calling Fetch Tool (Legacy Endpoint)"
info "Fetching URL: https://example.com"

curl -s -X POST $API/containers/$CID/mcp/fetchurl/fetch $HDR \
  -H "Content-Type:application/json" \
  -d '{"params":{"url":"https://example.com"}, "timeout": 10}' | jq '.'

# Use MCP proxy with JSON-RPC 2.0
headline "Using MCP Proxy with JSON-RPC 2.0"
info "Initializing MCP echo server via proxy"

# Initialize echo server
INIT_RESPONSE=$(curl -s -X POST $API/containers/$CID/mcp-proxy/echo $HDR \
  -H "Content-Type:application/json" \
  -d '{"jsonrpc":"2.0","method":"initialize","params":{"protocol_version":"2025-03-26"},"id":1}')

echo $INIT_RESPONSE | jq '.'

# Get session ID from response headers
SESSION_ID=$(curl -s -X POST $API/containers/$CID/mcp-proxy/echo $HDR \
  -H "Content-Type:application/json" \
  -d '{"jsonrpc":"2.0","method":"initialize","params":{"protocol_version":"2025-03-26"},"id":1}' \
  -D - | grep -i "Mcp-Session-Id" | cut -d' ' -f2 | tr -d '\r')

success "MCP session established with ID: $SESSION_ID"

# List tools
info "Listing tools via proxy"
curl -s -X POST $API/containers/$CID/mcp-proxy/echo $HDR \
  -H "Content-Type:application/json" \
  -H "Mcp-Session-Id: $SESSION_ID" \
  -d '{"jsonrpc":"2.0","method":"tools/list","id":2}' | jq '.'

# Call echo tool via proxy
info "Calling echo tool via proxy"
curl -s -X POST $API/containers/$CID/mcp-proxy/echo $HDR \
  -H "Content-Type:application/json" \
  -H "Mcp-Session-Id: $SESSION_ID" \
  -d '{"jsonrpc":"2.0","method":"tools/call","params":{"tool_name":"echo","params":{"message":"Hello via MCP Proxy!"}},"id":3}' | jq '.'

# Stream response example
headline "Streaming Response via SSE"
info "Calling echo tool with streaming response"
echo "Press Ctrl+C to stop streaming after a few seconds..."

curl -N -X POST $API/containers/$CID/mcp-proxy/echo $HDR \
  -H "Content-Type:application/json" \
  -H "Accept: text/event-stream" \
  -H "Mcp-Session-Id: $SESSION_ID" \
  -d '{"jsonrpc":"2.0","method":"tools/call","params":{"tool_name":"echo","params":{"message":"Hello streaming world!"}},"id":4}' &

CURL_PID=$!
sleep 3
kill $CURL_PID 2>/dev/null

# Clean up
headline "Cleaning Up"
info "Destroying container: $CID"

curl -s -X DELETE $API/containers/$CID $HDR > /dev/null
success "Container destroyed successfully"

headline "Demo Completed Successfully"
echo -e "${GREEN}All MCP functionality has been demonstrated successfully!${NC}"
echo -e "${YELLOW}You can try more examples with the test_mcp_proxy.py and test_mcp_tools_detail.py scripts.${NC}"
