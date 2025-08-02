# ipybox MCP Proxy Guide

Welcome to the **MCP Proxy** layer of *ipybox-server*.  
This document explains why the proxy exists, how it complements the legacy MCP helper routes, and how to interact with it using the official **Model-Context-Protocol (MCP)** specification – **Streamable HTTP** + **JSON-RPC 2.0**.

---

## 1. What the MCP Proxy Does

* Converts **HTTP POST** requests that follow the MCP Streamable HTTP spec into **stdio JSON-RPC** messages for a server running **inside the container**.  
* Streams the server’s replies back to the client as either  
  * `Content-Type: application/json` (simple or batch) or  
  * `Content-Type: text/event-stream` (Server-Sent Events).

Think of it as a **reverse API gateway** that makes any `stdio`-only MCP server reachable to web and cloud clients.

---

## 2. How It Differs From the “Old” MCP Helper End-points

| Feature | Legacy `/mcp/{server}`                 | New `/mcp-proxy/{server}` |
|---------|----------------------------------------|---------------------------|
| Transport | Custom helper wrappers written for ipybox | **Spec-compliant MCP Streamable HTTP** |
| Protocol level | “Tool per route” helpers only | **Full JSON-RPC 2.0** (initialize, notifications, batching, custom methods) |
| Streaming | Blocking only                       | **SSE streaming** or JSON |
| Session | Ephemeral per request                 | **Persistent session** with `Mcp-Session-Id` |
| Server type | Requires python-generator sources | Works with any **stdio MCP server** (via supergateway) |
| Tool discovery | Additional helper route        | Native `tools/list`, `tools/call` |

Use the old routes if you only need the quick helpers; use the proxy if you need drop-in interoperability with the wider MCP ecosystem (Claude Desktop, Superinterface, LiteLLM, etc.).

---

## 3. MCP Compliance

* **Message format**: JSON-RPC 2.0 (`jsonrpc: "2.0"`, `method`, `params`, `id`…)  
* **Transport**: Streamable HTTP revision 2025-03-26  
  * HTTP POST for client-to-server messages  
  * HTTP GET or POST → `text/event-stream` for server-to-client streaming  
  * Batching and notifications supported  
* **Sessions**: header `Mcp-Session-Id` (opaque string)

---

## 4. API Specification

### 4.1 End-points

| Method | Path | Description |
|--------|------|-------------|
| POST | `/containers/{cid}/mcp-proxy/{server}` | Send one JSON-RPC request or batch. Returns JSON or SSE depending on `Accept`. |

### 4.2 Required / Optional Headers

Header | Direction | Purpose
-------|-----------|---------
`X-API-Key` | → | (if server auth enabled)
`Content-Type: application/json` | → | Request body
`Accept: application/json, text/event-stream` | → | Choose JSON or SSE  
`Mcp-Session-Id` | ↔ | Stick subsequent requests to the same subprocess
`Mcp-Session-Id` (response) | ← | Newly created session id

---

## 5. Session Management

1. First call **omits** `Mcp-Session-Id`.  
2. Proxy spawns (or re-uses) a subprocess running the MCP server (usually via **supergateway**).  
3. Response carries a fresh header `Mcp-Session-Id: mcp-<uuid>`.  
4. Include that value in every further request header to keep the same context alive.  
5. Sessions are auto-terminated if idle for `IPYBOX_MAX_IDLE_TIME` (default 3600 s).

---

## 6. Response Formats

### 6.1 JSON

```
POST /mcp-proxy/echo
Accept: application/json

{ "jsonrpc":"2.0", "method":"initialize", "id":1 }
```

Response:

```json
{
  "jsonrpc": "2.0",
  "result": { "serverInfo": { "name": "echo" } },
  "id": 1
}
```

### 6.2 Server-Sent Events (SSE)

```
POST /mcp-proxy/echo
Accept: text/event-stream
```

Stream:

```
data: {"jsonrpc":"2.0","result":{...},"id":1}

data: [DONE]
```

Each `data:` line is a complete JSON-RPC message.

---

## 7. Using Different MCP Servers

1. **Register** the server (once) with the legacy helper:

```
PUT /containers/{cid}/mcp/echo
{
  "server_params": {
    "command": "uvx",
    "args": ["mcp-server-echo"]
  }
}
```

2. Thereafter call via the proxy: `/mcp-proxy/echo`.

You can register **multiple** servers in the same container; each keeps its own session space.

---

## 8. Supergateway Integration

The proxy internally launches:

```
uvx supergateway --stdio "mcp-server-{server}"
```

* Converts stdio JSON-RPC ↔ HTTP/SSE automatically.  
* No user action required, but you may override the command/args when registering if you ship a custom binary.

---

## 9. Curl Cheat-Sheet

```bash
API=http://localhost:8000
CID=$(curl -s -X POST $API/containers -H "Content-Type:application/json" \
        -d '{"tag":"ghcr.io/gradion-ai/ipybox"}' | jq -r .id)

# Register stdio server
curl -X PUT $API/containers/$CID/mcp/echo \
     -H "Content-Type:application/json" \
     -d '{"server_params":{"command":"uvx","args":["mcp-server-echo"]}}'

# 1. initialize (JSON)
curl -s -X POST $API/containers/$CID/mcp-proxy/echo \
     -H "Content-Type:application/json" \
     -d '{"jsonrpc":"2.0","method":"initialize","id":1}' | jq

# 2. list tools (reuse session)
curl -s -X POST $API/containers/$CID/mcp-proxy/echo \
     -H "Content-Type:application/json" -H "Mcp-Session-Id: mcp-<id>" \
     -d '{"jsonrpc":"2.0","method":"tools/list","id":2}' | jq

# 3. call tool (SSE streaming)
curl -N -X POST $API/containers/$CID/mcp-proxy/echo \
     -H "Content-Type:application/json" \
     -H "Accept:text/event-stream" \
     -H "Mcp-Session-Id: mcp-<id>" \
     -d '{"jsonrpc":"2.0","method":"tools/call","params":{"tool_name":"echo","params":{"message":"hi"}},"id":3}'
```

---

## 10. Python Client Example

```python
import asyncio, json, aiohttp

async def main():
    API = "http://localhost:8000"
    async with aiohttp.ClientSession() as s:
        # create container
        r = await s.post(f"{API}/containers", json={"tag":"ghcr.io/gradion-ai/ipybox"})
        cid = (await r.json())["id"]

        # register echo server
        await s.put(f"{API}/containers/{cid}/mcp/echo",
                    json={"server_params":{"command":"uvx","args":["mcp-server-echo"]}})

        headers = {"Content-Type":"application/json"}
        # initialize
        resp = await s.post(f"{API}/containers/{cid}/mcp-proxy/echo",
                            json={"jsonrpc":"2.0","method":"initialize","id":1}, headers=headers)
        sid = resp.headers.get("Mcp-Session-Id")
        print("init:", await resp.json())

        # list tools
        headers["Mcp-Session-Id"] = sid
        resp = await s.post(f"{API}/containers/{cid}/mcp-proxy/echo",
                            json={"jsonrpc":"2.0","method":"tools/list","id":2}, headers=headers)
        print("tools:", await resp.json())

        # call tool (JSON)
        req = {"jsonrpc":"2.0","method":"tools/call",
               "params":{"tool_name":"echo","params":{"message":"Hello"}}, "id":3}
        resp = await s.post(f"{API}/containers/{cid}/mcp-proxy/echo", json=req, headers=headers)
        print("result:", await resp.json())

asyncio.run(main())
```

---

## 11. Error Handling & Troubleshooting

HTTP Status | JSON-RPC error.code | Cause | Fix
----------- | ------------------ | ----- | ---
400 | ‑32700 / ‑32600 | Malformed JSON-RPC | Validate request
401 | n/a | Missing / wrong API key | Set `X-API-Key`
404 | n/a | Container or server not found | Check IDs
500 | ‑32603 | Internal proxy / subprocess error | Inspect logs (`IPYBOX_LOG_LEVEL=DEBUG`)
504 | custom | Timeout waiting for server | Increase idle/timeout or debug server

Set `IPYBOX_LOG_LEVEL=DEBUG` to see stdio of the MCP server.

---

## 12. Performance Considerations

* **Session reuse** avoids cold-start up to 400 ms per call.  
* Idle cleanup prevents zombie processes – tune via `IPYBOX_MAX_IDLE_TIME`.  
* For high QPS, run multiple containers and load-balance at the HTTP layer.

---

## 13. Security Notes

* **Isolation** – still Docker-sandboxed with optional firewall.  
* **Auth** – same API-key gate as the rest of ipybox.  
* **Session IDs** are random UUID strings – treat as bearer tokens; transmit over TLS.  
* **Resource limits** – constrain CPU/MEM on Docker hosts to protect against runaway MCP servers.  
* **Input validation** – proxy validates JSON-RPC structure before forwarding to avoid injection of non-conforming data.

---

## 14. Complete Lifecycle Example (Side-by-Side)

| Step | Legacy Helpers | New Proxy |
|------|----------------|-----------|
| Register server | `PUT /mcp/{srv}` | same |
| List tools | `GET /mcp/{srv}` | `tools/list` JSON-RPC |
| Call tool | `POST /mcp/{srv}/{tool}` | `tools/call` JSON-RPC |
| Streaming | not supported | SSE |
| Batch | not supported | Supported |
| Version negotiation | none | `initialize` |

Use whichever layer matches your client requirements. For anything that calls itself “MCP client” choose the proxy.

---

Happy hacking – and welcome to the MCP ecosystem 🎉
