API=http://localhost:8000
KEY="mysecret"          # omit if auth disabled
HDR="-H X-API-Key:$KEY"


CID=$(curl -s -X POST $API/containers $HDR -H "Content-Type:application/json" \
        -d '{"tag":"ghcr.io/gradion-ai/ipybox:minimal"}' | jq -r .id)

# Register stdio server
curl -X PUT $API/containers/$CID/mcp/fetchurl $HDR \
     -H "Content-Type:application/json" \
     -d '{"server_params":{"command":"uvx","args":["mcp-server-fetch"]}}'

# 1. initialize (JSON)
curl -s -X POST $API/containers/$CID/mcp-proxy/fetchurl \
     -H "Content-Type:application/json" \
     -d '{"jsonrpc":"2.0","method":"initialize","id":1}' | jq

# # 2. list tools (reuse session)
# curl -s -X POST $API/containers/$CID/mcp-proxy/echo \
#      -H "Content-Type:application/json" -H "Mcp-Session-Id: mcp-<id>" \
#      -d '{"jsonrpc":"2.0","method":"tools/list","id":2}' | jq

# # 3. call tool (SSE streaming)
# curl -N -X POST $API/containers/$CID/mcp-proxy/echo \
#      -H "Content-Type:application/json" \
#      -H "Accept:text/event-stream" \
#      -H "Mcp-Session-Id: mcp-<id>" \
#      -d '{"jsonrpc":"2.0","method":"tools/call","params":{"tool_name":"echo","params":{"message":"hi"}},"id":3}'