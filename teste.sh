API=http://localhost:8000
KEY="mysecret"          # omit if auth disabled
HDR="-H X-API-Key:$KEY"

# Create container
CID=$(curl -s -X POST $API/containers $HDR -H "Content-Type:application/json" \
      -d '{"tag":"ghcr.io/ghcr.io/gradion-ai/ipybox:minimal"}' | jq -r .id)

# Execute code
curl -s -X POST $API/containers/$CID/execute $HDR \
     -H "Content-Type:application/json" \
     -d '{"code":"print(2+2)"}' | jq

# Stream execution
curl -N -X POST $API/containers/$CID/execute/stream $HDR \
     -H "Content-Type:application/json" \
     -d '{"code":"import time\nfor i in range(3):\n print(i); time.sleep(1)"}'

# Destroy container
curl -X DELETE $API/containers/$CID $HDR

