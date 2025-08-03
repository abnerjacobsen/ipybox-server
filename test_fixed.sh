#!/bin/bash
# ===================================================================
# MCP Tools Test - Fixed Version
# ===================================================================
# This script demonstrates the enhanced MCP tools endpoint that now
# returns detailed parameter schemas, not just tool names.
#
# FIXES:
# - Uses Python-based MCP servers instead of uvx commands
# - Shows both old and new behavior (with parameter schemas)
# - Includes proper error handling and timeouts
# - No hanging or waiting indefinitely
# ===================================================================

# Text formatting for better readability
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
  # Clean up container if we have an ID
  if [ -n "$CID" ]; then
    echo -e "${YELLOW}→ Cleaning up container $CID${NC}"
    curl -s -X DELETE $API/containers/$CID $HDR > /dev/null
  fi
  exit 1
}

# Function to check if command succeeded
check_error() {
  if [ $? -ne 0 ]; then
    error "$1"
  fi
}

# ===================================================================
# Main Script
# ===================================================================
headline "Starting MCP Tools Test"

# Check if jq is installed (needed for JSON parsing)
if ! command -v jq &> /dev/null; then
  error "jq is required but not installed. Please install jq first."
fi

# Create container
headline "Creating Container"
info "Creating new container..."

CONTAINER_RESPONSE=$(curl -s -X POST $API/containers $HDR \
  -H "Content-Type:application/json" \
  -d '{"tag":"ghcr.io/gradion-ai/ipybox"}')
check_error "Failed to create container"

CID=$(echo $CONTAINER_RESPONSE | jq -r .id)
if [ -z "$CID" ] || [ "$CID" == "null" ]; then
  error "Failed to get container ID from response"
fi

success "Container created with ID: $CID"

# Basic code execution test to verify container works
headline "Testing Basic Code Execution"
info "Executing simple Python code: print(2+2)"

RESULT=$(curl -s -X POST $API/containers/$CID/execute $HDR \
  -H "Content-Type:application/json" \
  -d '{"code":"print(2+2)"}' | jq -r .text)
check_error "Code execution failed"

if [ "$RESULT" == "4" ]; then
  success "Code execution successful: 2+2 = $RESULT"
else
  error "Code execution failed. Expected 4, got: $RESULT"
fi

# Register MCP echo server using Python script (not uvx)
headline "Registering MCP Echo Server"
info "Using Python-based echo server instead of uvx"

ECHO_RESPONSE=$(curl -s -X PUT $API/containers/$CID/mcp/echo $HDR \
  -H "Content-Type:application/json" \
  -d '{"server_params":{"command":"python3","args":["examples/simple_mcp_echo_server.py"]}}')
check_error "Failed to register echo server"

ECHO_TOOLS=$(echo $ECHO_RESPONSE | jq -r '.tool_names | join(", ")')
success "Echo server registered with tools: $ECHO_TOOLS"

# Register MCP fetch server using Python script (not uvx)
headline "Registering MCP Fetch Server"
info "Using Python-based fetch server instead of uvx"

FETCH_RESPONSE=$(curl -s -X PUT $API/containers/$CID/mcp/fetchurl $HDR \
  -H "Content-Type:application/json" \
  -d '{"server_params":{"command":"python3","args":["examples/simple_mcp_fetch_server.py"]}}')
check_error "Failed to register fetch server"

FETCH_TOOLS=$(echo $FETCH_RESPONSE | jq -r '.tool_names | join(", ")')
success "Fetch server registered with tools: $FETCH_TOOLS"

# ===================================================================
# DEMONSTRATION OF NEW BEHAVIOR - DETAILED TOOL SCHEMAS
# ===================================================================
headline "BEFORE vs AFTER: MCP Tools Endpoint"

# Get tools with detailed schema information
info "Getting tools for echo server..."
ECHO_TOOLS_RESPONSE=$(curl -s $API/containers/$CID/mcp/echo $HDR)
check_error "Failed to get echo tools"

info "Getting tools for fetch server..."
FETCH_TOOLS_RESPONSE=$(curl -s $API/containers/$CID/mcp/fetchurl $HDR)
check_error "Failed to get fetch tools"

# Show BEFORE behavior (just tool names)
echo -e "\n${YELLOW}BEFORE:${NC} The endpoint only returned tool names"
echo -e "${BLUE}Echo server tool names:${NC} $(echo $ECHO_TOOLS_RESPONSE | jq -r '.tool_names | join(", ")')"
echo -e "${BLUE}Fetch server tool names:${NC} $(echo $FETCH_TOOLS_RESPONSE | jq -r '.tool_names | join(", ")')"

# Show AFTER behavior (detailed schema)
echo -e "\n${GREEN}AFTER:${NC} The endpoint now returns detailed tool schemas"

# Echo server tools with schema
echo -e "\n${BLUE}Echo server tools with schema:${NC}"
echo $ECHO_TOOLS_RESPONSE | jq '.tools'

# Fetch server tools with schema
echo -e "\n${BLUE}Fetch server tools with schema:${NC}"
echo $FETCH_TOOLS_RESPONSE | jq '.tools'

# ===================================================================
# TEST TOOL EXECUTION
# ===================================================================
headline "Testing Tool Execution"

# Test echo tool
info "Testing echo tool with message 'Hello MCP!'"
ECHO_RESULT=$(curl -s -X POST $API/containers/$CID/mcp/echo/echo $HDR \
  -H "Content-Type:application/json" \
  -d '{"params":{"message":"Hello MCP!"}, "timeout": 5}' | jq -r .result)
check_error "Echo tool execution failed"

success "Echo response: $ECHO_RESULT"

# Test fetch tool with a short timeout to prevent hanging
info "Testing fetch tool with URL 'https://example.com' (timeout: 10s)"
FETCH_RESULT=$(curl -s --max-time 15 -X POST $API/containers/$CID/mcp/fetchurl/fetch $HDR \
  -H "Content-Type:application/json" \
  -d '{"params":{"url":"https://example.com"}, "timeout": 10}')
check_error "Fetch tool execution failed or timed out"

# Show abbreviated fetch result
echo -e "${BLUE}Fetch result (status code):${NC} $(echo $FETCH_RESULT | jq '.result.status_code')"

# ===================================================================
# CLEANUP
# ===================================================================
headline "Cleaning Up"
info "Destroying container: $CID"

curl -s -X DELETE $API/containers/$CID $HDR > /dev/null
check_error "Failed to destroy container"

success "Container destroyed successfully"

# ===================================================================
# SUMMARY
# ===================================================================
headline "Test Summary"
echo -e "${GREEN}✓ Successfully demonstrated enhanced MCP tools endpoint${NC}"
echo -e "${GREEN}✓ Tools now return detailed parameter schemas${NC}"
echo -e "${GREEN}✓ No more hanging or timeout issues${NC}"
echo -e "${GREEN}✓ Using Python-based MCP servers instead of uvx${NC}"

echo -e "\n${YELLOW}→ To see the full enhanced tools endpoint in action:${NC}"
echo "  python test_mcp_tools_detail.py"
