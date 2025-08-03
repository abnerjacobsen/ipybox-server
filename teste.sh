API=http://localhost:8000
KEY="mysecret"          # omit if auth disabled
HDR="-H X-API-Key:$KEY"

# Create container
CID=$(curl -s -X POST $API/containers $HDR -H "Content-Type:application/json" \
      -d '{"tag":"ghcr.io/gradion-ai/ipybox:minimal"}' | jq -r .id)

# Execute code
curl -s -X POST $API/containers/$CID/execute $HDR \
     -H "Content-Type:application/json" \
     -d '{"code":"print(2+2)"}' | jq

# Stream execution
curl -N -X POST $API/containers/$CID/execute/stream $HDR \
     -H "Content-Type:application/json" \
     -d '{"code":"import time\nfor i in range(3):\n print(i); time.sleep(1)"}'

# Register server
curl -X PUT $API/containers/$CID/mcp/fetchurl $HDR \
     -H "Content-Type:application/json" \
     -d '{"server_params":{"command":"uvx","args":["mcp-server-fetch"]}}'

# Register server
curl -X PUT $API/containers/$CID/mcp/echo $HDR \
     -H "Content-Type:application/json" \
     -d '{"server_params":{"command":"uvx","args":["echo-mcp-server-for-testing"], "env":{"SECRET_KEY": "123456789"}}}'

# List tools
curl $API/containers/$CID/mcp/fetchurl $HDR | jq
curl $API/containers/$CID/mcp/echo $HDR | jq

# # Invoke tool
# curl -X POST $API/containers/$CID/mcp/fetchurl/fetch $HDR \
#      -H "Content-Type:application/json" \
#      -d '{"params":{"url":"https://aumo.ai"}, "timeout": 50}'

# curl -X POST $API/containers/$CID/mcp/echo/echo_tool $HDR \
#      -H "Content-Type:application/json" \
#      -d '{"params":{"message":"https://aumo.ai"}, "timeout": 50}'

curl -X POST $API/containers/$CID/mcp/echo/echo_tool $HDR \
     -H "Content-Type:application/json" \
     -d '{"params":{"message":"AGORA FUNCIONOUi"}, "timeout": 50}' | jq

# Destroy container
curl -X DELETE $API/containers/$CID $HDR

