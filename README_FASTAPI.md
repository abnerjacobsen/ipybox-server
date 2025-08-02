# ipybox FastAPI Server Guide

Welcome to the ipybox **FastAPI** server.  
This document explains how to run ipybox as a network service and interact with it programmatically.

---

## 1. Overview

ipybox is a lightweight, Docker-backed sandbox that executes Python code in isolated IPython kernels.  
The new FastAPI layer turns ipybox into a **REST service** that lets you:

* Spin-up disposable execution containers on demand  
* Execute code (blocking or streaming) and retrieve results  
* Upload, download and delete files & directories inside containers  
* Register and call **MCP** (Model Context Protocol) servers/tools  
* Configure a container firewall for outbound network whitelisting  
* Monitor and clean up containers automatically

Everything is asynchronous, container-scoped and protected by an optional API key.

---

## 2. Installation & Setup

```bash
# 1. Clone your repository
git clone <your-fork-url>
cd ipybox-server

# 2. Install python dependencies
pip install -e ".[dev]"

# 3. Ensure Docker is installed and running
docker info

# 4. Start the server (default 0.0.0.0:8000)
python run_server.py
```

Hot-reload (development):

```bash
python run_server.py --dev
```

---

## 3. Configuration Options

Environment variable (or CLI flag) | Purpose | Default
----------------------------------|---------|---------
`IPYBOX_HOST` | Bind address | `0.0.0.0`
`IPYBOX_PORT` | Bind port | `8000`
`IPYBOX_API_KEY` | API-key string. Empty disables auth | *empty*
`IPYBOX_DEFAULT_TAG` | Default Docker image | `ghcr.io/gradion-ai/ipybox`
`IPYBOX_CLEANUP_INTERVAL` | Seconds between idle-check passes | `300`
`IPYBOX_MAX_IDLE_TIME` | Seconds of inactivity before container removal | `3600`
`IPYBOX_CORS_ORIGINS` | Comma-separated CORS origins | `*`
`IPYBOX_LOG_LEVEL` | Logging level | `INFO`

CLI flags mirror the variables (see `python run_server.py --help`).

---

## 4. Authentication

* **Header name:** `X-API-Key`  
* **Enable auth:** set `IPYBOX_API_KEY="mysecret"` (or `--api-key mysecret`)  
* **Disable auth:** leave the variable empty.

All requests except `/health` require the header when auth is enabled.

---

## 5. API End-Points (Summary)

Method | Path | Description
------ | ---- | -----------
GET | `/health` | Service liveness probe
POST | `/containers` | Create execution container
GET | `/containers` | List containers
GET | `/containers/{id}` | Inspect container
DELETE | `/containers/{id}` | Destroy container
POST | `/containers/{id}/firewall` | Set outbound allow-list
POST | `/containers/{id}/execute` | Run code (blocking)
POST | `/containers/{id}/execute/stream` | Run code (Server-Sent Events)
GET | `/executions/{exe_id}` | Inspect execution
PUT | `/containers/{id}/mcp/{server}` | Register MCP server
GET | `/containers/{id}/mcp/{server}` | List MCP tools
POST | `/containers/{id}/mcp/{server}/{tool}` | Call MCP tool
POST/GET/DELETE | `/containers/{id}/files/{path}` | Upload / download / delete file
POST/GET | `/containers/{id}/directories/{path}` | Upload / download tar.gz directory

Detailed schemas are available via the automatic `/docs` (Swagger UI) and `/redoc` endpoints.

---

## 6. Quick Curl Examples

```bash
API=http://localhost:8000
KEY="mysecret"          # omit if auth disabled
HDR="-H X-API-Key:$KEY"

# Create container
CID=$(curl -s -X POST $API/containers $HDR -H "Content-Type:application/json" \
      -d '{"tag":"ghcr.io/gradion-ai/ipybox"}' | jq -r .id)

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
```

---

## 7. Python Client Usage

```python
import asyncio
from examples.fastapi_server_demo import IpyboxClient   # already included in repo

async def main():
    async with IpyboxClient("localhost", 8000, api_key="mysecret") as cli:
        c = await cli.create_container()
        cid = c["id"]
        res = await cli.execute_code(cid, "print('Hello')")
        print(res["text"])
        await cli.destroy_container(cid)

asyncio.run(main())
```

---

## 8. MCP Integration

1. **Register server**

```bash
curl -X PUT $API/containers/$CID/mcp/fetchurl $HDR \
     -H "Content-Type:application/json" \
     -d '{"server_params":{"command":"uvx","args":["mcp-server-fetch"]}}'
```

2. **List tools**

```bash
curl $API/containers/$CID/mcp/fetchurl $HDR
```

3. **Invoke tool**

```bash
curl -X POST $API/containers/$CID/mcp/fetchurl/fetch $HDR \
     -H "Content-Type:application/json" \
     -d '{"params":{"url":"https://example.com"}}'
```

---

## 9. File Operations

```bash
# Upload a local file
curl -F "file=@README.md" $HDR \
     $API/containers/$CID/files/docs

# Download it back
curl $HDR -o README_copy.md \
     $API/containers/$CID/files/docs/README.md

# Delete
curl -X DELETE $API/containers/$CID/files/docs/README.md $HDR
```

Upload / download entire directories via tar.gz archives:

```bash
# Upload dir
tar czf data.tar.gz data_dir
curl -F "file=@data.tar.gz;type=application/x-gzip" $HDR \
     $API/containers/$CID/directories/project

# Download dir
curl $HDR -o project.tar.gz \
     $API/containers/$CID/directories/project
```

---

## 10. Container Lifecycle

1. Create (`POST /containers`)  
2. Optionally initialise firewall  
3. Execute code / manage files / call MCP  
## 14. MCP Proxy (NEW!)

The ipybox server now ships with a **spec-compliant MCP Proxy** that implements the **Streamable HTTP** transport defined by the Model Context Protocol (MCP).

### 14.1 Why a Proxy?

The original MCP helper routes (`/mcp/{server}`) wrap individual tools with convenience
end-points.  
The new proxy exposes the **full MCP JSON-RPC 2.0 interface** so you can connect
third-party MCP clients such as **Claude Desktop**, **LiteLLM Gateway**, **FastMCP**, etc.

| Feature | Legacy `/mcp/{server}` | New `/mcp-proxy/{server}` |
|---------|-----------------------|---------------------------|
| Protocol layer | Custom helpers | **Official MCP Streamable HTTP** |
| Message format | Tool-specific REST | **JSON-RPC 2.0** (batch & notifications) |
| Streaming | Blocking only | **SSE streaming** |
| Session model | Per-request | **Persistent sessions** (`Mcp-Session-Id`) |
| Ecosystem | ipybox only | Works with any MCP client |

### 14.2 Proxy Endpoint

| Method | Path | Description |
|--------|------|-------------|
| POST | `/containers/{id}/mcp-proxy/{server}` | Send JSON-RPC message or batch |

Headers:

* `X-API-Key` – authentication (if enabled)  
* `Content-Type: application/json` – request body  
* `Accept: application/json` **or** `text/event-stream` – choose response format  
* `Mcp-Session-Id` – (optional) continue an existing session

### 14.3 Example Workflow

```bash
# 1) Initialize (creates session)
curl -X POST $API/containers/$CID/mcp-proxy/echo \
     -H 'Content-Type: application/json' \
     -d '{"jsonrpc":"2.0","method":"initialize","id":1}'
# ↳ Response header will contain Mcp-Session-Id: mcp-123…

# 2) List tools (reuse session)
curl -X POST $API/containers/$CID/mcp-proxy/echo \
     -H 'Content-Type: application/json' \
     -H 'Mcp-Session-Id: mcp-123' \
     -d '{"jsonrpc":"2.0","method":"tools/list","id":2}'

# 3) Call a tool (JSON)
curl -X POST $API/containers/$CID/mcp-proxy/echo \
     -H 'Content-Type: application/json' \
     -H 'Mcp-Session-Id: mcp-123' \
     -d '{"jsonrpc":"2.0","method":"tools/call","params":{"tool_name":"echo","params":{"message":"Hello"}},"id":3}'

# 4) Call the same tool with **SSE streaming**
curl -N -X POST $API/containers/$CID/mcp-proxy/echo \
     -H 'Content-Type: application/json' \
     -H 'Accept: text/event-stream' \
     -H 'Mcp-Session-Id: mcp-123' \
     -d '{"jsonrpc":"2.0","method":"tools/call","params":{"tool_name":"echo","params":{"message":"Hello-SSE"}},"id":4}'
```

### 14.4 Session Lifecycle

1. First request ⇒ proxy spawns stdio MCP server (via **supergateway**)  
2. Response returns `Mcp-Session-Id` header  
3. Include that ID in subsequent calls to maintain context  
4. Sessions auto-expire after the idle timeout (`IPYBOX_MAX_IDLE_TIME`, default 1 h)

### 14.5 Legacy vs Proxy Quick Reference

```bash
# Legacy helper (still works)
curl -X POST $API/containers/$CID/mcp/echo/echo \
     -d '{"params":{"message":"Hi"}}'

# Proxy – full MCP
curl -X POST $API/containers/$CID/mcp-proxy/echo \
     -d '{"jsonrpc":"2.0","method":"tools/call","params":{"tool_name":"echo","params":{"message":"Hi"}},"id":1}'
```

**Key wins:** full spec compliance, batch requests, real-time SSE, persistent sessions & compatibility with the broader MCP ecosystem.

For an end-to-end demo see `examples/mcp_proxy_demo.py` and the dedicated
`README_MCP_PROXY.md`.

4. Destroy (`DELETE /containers/{id}`) *or* let idle-cleanup remove it automatically.

Lifecycle metadata (`created_at`, `last_used_at`, `status`) is reported in every container object.

---

## 11. Security Considerations

* **Isolation** – code runs inside Docker with no host network by default.  
* **Firewall** – allowlist outbound domains/IPs per container.  
* **Auth** – API key header, TLS recommended in production (reverse-proxy).  
* **Resource limits** – run Docker with CPU/memory quotas if needed.  
* **Image trust** – use a custom ipybox image or pin digest.

---

## 12. Troubleshooting

Symptom | Cause | Fix
------- | ----- | ---
`401 Unauthorized` | Missing/invalid API key | Set `X-API-Key` header
`500 Failed to create container` | Docker not running / image pull error | `docker info`, check network, set `IPYBOX_DEFAULT_TAG`
Execution hangs | Long-running code | Increase `timeout` field or debug code
`ConnectionRefused` to `/execute` | Container not ready yet | Wait a few seconds; the server already retries but slow hosts may need longer
`Cannot pull image` | No registry access | Pre-pull image or use local build

Debug logs at `IPYBOX_LOG_LEVEL=DEBUG`.

---

## 13. Development & Testing

```bash
# Run unit + integration tests
pytest -q

# Lint & type check
invoke code-check          # or: ruff / mypy

# Build docs
invoke build-docs

# Start server with autoreload & debug
python run_server.py --dev --log-level DEBUG
```

To regenerate the Python demo client:

```bash
python examples/fastapi_server_demo.py --host localhost --port 8000 --api-key mysecret
```

---

Happy hacking – feel free to open issues or pull requests!
