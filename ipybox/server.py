import asyncio
import logging
import os
import uuid
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Union

import aiofiles
import aiofiles.os
import json
from fastapi import Depends, FastAPI, File, HTTPException, Path as PathParam, Query, Request, Response, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, Field, validator

from ipybox import ExecutionClient, ExecutionContainer, ResourceClient
from ipybox.mcp_proxy import create_mcp_proxy, mcp_proxy_lifecycle
from ipybox.executor import ExecutionError, ExecutionResult
from ipybox.mcp.run import run_async

# Standard library
from contextlib import asynccontextmanager

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("ipybox.server")

# API Key authentication
API_KEY_NAME = "X-API-Key"
API_KEY = os.environ.get("IPYBOX_API_KEY", "")
api_key_header = APIKeyHeader(name=API_KEY_NAME, auto_error=False)

# Default Docker image tag
DEFAULT_DOCKER_TAG = os.environ.get("IPYBOX_DEFAULT_TAG", "ghcr.io/gradion-ai/ipybox")

# Container cleanup settings
CONTAINER_CLEANUP_INTERVAL = int(os.environ.get("IPYBOX_CLEANUP_INTERVAL", "300"))  # 5 minutes
CONTAINER_MAX_IDLE_TIME = int(os.environ.get("IPYBOX_MAX_IDLE_TIME", "3600"))  # 1 hour

# ==================== Pydantic Models ====================

class ErrorResponse(BaseModel):
    detail: str


class ContainerConfig(BaseModel):
    tag: str = DEFAULT_DOCKER_TAG
    binds: Dict[str, str] = Field(default_factory=dict)
    env: Dict[str, str] = Field(default_factory=dict)
    executor_port: Optional[int] = None
    resource_port: Optional[int] = None
    show_pull_progress: bool = False


class ContainerInfo(BaseModel):
    id: str
    tag: str
    executor_port: int
    resource_port: int
    created_at: datetime
    last_used_at: datetime
    status: str


class FirewallConfig(BaseModel):
    allowed_domains: List[str] = Field(default_factory=list)


class CodeExecutionRequest(BaseModel):
    code: str
    timeout: float = 120.0


class CodeExecutionResponse(BaseModel):
    execution_id: str
    text: Optional[str] = None
    has_images: bool = False
    error: Optional[str] = None
    error_trace: Optional[str] = None
    completed: bool = True


class ExecutionStatus(BaseModel):
    execution_id: str
    container_id: str
    status: str
    created_at: datetime
    completed_at: Optional[datetime] = None
    error: Optional[str] = None


class MCPServerConfig(BaseModel):
    server_params: Dict[str, Any]


class MCPToolRequest(BaseModel):
    params: Dict[str, Any]
    timeout: float = 5.0


class MCPToolResponse(BaseModel):
    result: Optional[str] = None
    error: Optional[str] = None

# ==================== State Management ====================

class ContainerManager:
    def __init__(self):
        self.containers: Dict[str, ExecutionContainer] = {}
        self.container_info: Dict[str, ContainerInfo] = {}
        self.executions: Dict[str, Dict[str, Any]] = {}
        self.cleanup_task = None
        self.lock = asyncio.Lock()

    async def start_cleanup_task(self):
        self.cleanup_task = asyncio.create_task(self._cleanup_containers())

    async def stop_cleanup_task(self):
        if self.cleanup_task:
            self.cleanup_task.cancel()
            try:
                await self.cleanup_task
            except asyncio.CancelledError:
                pass

    async def _cleanup_containers(self):
        while True:
            try:
                await asyncio.sleep(CONTAINER_CLEANUP_INTERVAL)
                await self.cleanup_idle_containers()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in container cleanup task: {e}")

    async def cleanup_idle_containers(self):
        now = datetime.now()
        idle_threshold = now - timedelta(seconds=CONTAINER_MAX_IDLE_TIME)
        
        async with self.lock:
            container_ids = list(self.containers.keys())
            
        for container_id in container_ids:
            try:
                info = await self.get_container_info(container_id)
                if info.last_used_at < idle_threshold:
                    logger.info(f"Cleaning up idle container {container_id}")
                    await self.destroy_container(container_id)
            except Exception as e:
                logger.error(f"Error cleaning up container {container_id}: {e}")

    async def create_container(self, config: ContainerConfig) -> str:
        container_id = str(uuid.uuid4())
        
        try:
            container = ExecutionContainer(
                tag=config.tag,
                binds=config.binds,
                env=config.env,
                executor_port=config.executor_port,
                resource_port=config.resource_port,
                show_pull_progress=config.show_pull_progress,
            )
            
            await container.run()
            
            async with self.lock:
                self.containers[container_id] = container
                self.container_info[container_id] = ContainerInfo(
                    id=container_id,
                    tag=config.tag,
                    executor_port=container.executor_port,
                    resource_port=container.resource_port,
                    created_at=datetime.now(),
                    last_used_at=datetime.now(),
                    status="running"
                )
            
            return container_id
        
        except Exception as e:
            logger.error(f"Failed to create container: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to create container: {str(e)}"
            )

    async def get_container(self, container_id: str) -> ExecutionContainer:
        async with self.lock:
            container = self.containers.get(container_id)
            
        if not container:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Container {container_id} not found"
            )
        
        # Update last used timestamp
        await self.update_container_usage(container_id)
        
        return container

    async def get_container_info(self, container_id: str) -> ContainerInfo:
        async with self.lock:
            info = self.container_info.get(container_id)
            
        if not info:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Container {container_id} not found"
            )
            
        return info

    async def update_container_usage(self, container_id: str):
        async with self.lock:
            if container_id in self.container_info:
                self.container_info[container_id].last_used_at = datetime.now()

    async def destroy_container(self, container_id: str):
        async with self.lock:
            container = self.containers.pop(container_id, None)
            self.container_info.pop(container_id, None)
            
            # Remove associated executions
            execution_ids = [
                exec_id for exec_id, exec_info in self.executions.items()
                if exec_info.get("container_id") == container_id
            ]
            for exec_id in execution_ids:
                self.executions.pop(exec_id, None)
        
        if container:
            try:
                await container.kill()
                return True
            except Exception as e:
                logger.error(f"Error destroying container {container_id}: {e}")
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Failed to destroy container: {str(e)}"
                )
        
        return False

    async def list_containers(self) -> List[ContainerInfo]:
        async with self.lock:
            return list(self.container_info.values())

    async def register_execution(self, container_id: str, execution_id: str):
        async with self.lock:
            self.executions[execution_id] = {
                "container_id": container_id,
                "status": "running",
                "created_at": datetime.now(),
                "completed_at": None,
                "error": None
            }

    async def complete_execution(self, execution_id: str, error: Optional[str] = None):
        async with self.lock:
            if execution_id in self.executions:
                self.executions[execution_id]["status"] = "completed" if not error else "error"
                self.executions[execution_id]["completed_at"] = datetime.now()
                if error:
                    self.executions[execution_id]["error"] = error

    async def get_execution_status(self, execution_id: str) -> ExecutionStatus:
        async with self.lock:
            execution = self.executions.get(execution_id)
            
        if not execution:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Execution {execution_id} not found"
            )
            
        return ExecutionStatus(
            execution_id=execution_id,
            container_id=execution["container_id"],
            status=execution["status"],
            created_at=execution["created_at"],
            completed_at=execution["completed_at"],
            error=execution["error"]
        )


# Initialize container manager
container_manager = ContainerManager()

# ==================== Application Lifecycle ====================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifecycle manager that handles startup and shutdown"""
    logger.info("Starting ipybox server")
    
    # Start container manager cleanup task
    await container_manager.start_cleanup_task()
    
    # Create and start MCP proxy
    mcp_proxy = create_mcp_proxy(
        container_manager=container_manager,
        session_timeout=CONTAINER_MAX_IDLE_TIME,
        cleanup_interval=CONTAINER_CLEANUP_INTERVAL,
    )
    await mcp_proxy.start()
    
    # Add MCP proxy routes to the app
    app.include_router(mcp_proxy.create_router(), tags=["MCP Proxy"])
    
    # Store proxy in app state for access in endpoints
    app.state.mcp_proxy = mcp_proxy
    
    yield
    
    # Shutdown
    logger.info("Shutting down ipybox server")
    
    # Stop MCP proxy
    await mcp_proxy.stop()
    
    # Stop container manager
    await container_manager.stop_cleanup_task()
    
    # Clean up all containers
    container_ids = list(container_manager.containers.keys())
    for container_id in container_ids:
        try:
            await container_manager.destroy_container(container_id)
        except Exception as e:
            logger.error(f"Error destroying container {container_id} during shutdown: {e}")


# Create FastAPI app with lifespan
app = FastAPI(
    title="ipybox API",
    description="API for secure Python code execution in Docker containers with MCP proxy support",
    version="0.1.0",
    lifespan=lifespan,
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("IPYBOX_CORS_ORIGINS", "*").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ==================== Authentication ====================

async def verify_api_key(api_key: str = Depends(api_key_header)):
    if not API_KEY:
        # If no API key is set in environment, authentication is disabled
        return True
    
    if api_key != API_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
            headers={"WWW-Authenticate": API_KEY_NAME},
        )
    return True


# ==================== Health Check Endpoint ====================

@app.get("/health", tags=["Health"])
async def health_check():
    return {"status": "ok"}


# ==================== Container Management Endpoints ====================

@app.post("/containers", response_model=ContainerInfo, tags=["Containers"])
async def create_container(
    config: ContainerConfig,
    _: bool = Depends(verify_api_key)
):
    """Create a new execution container."""
    container_id = await container_manager.create_container(config)
    return await container_manager.get_container_info(container_id)


@app.get("/containers", response_model=List[ContainerInfo], tags=["Containers"])
async def list_containers(_: bool = Depends(verify_api_key)):
    """List all active containers."""
    return await container_manager.list_containers()


@app.get("/containers/{container_id}", response_model=ContainerInfo, tags=["Containers"])
async def get_container_info(
    container_id: str = PathParam(...),
    _: bool = Depends(verify_api_key)
):
    """Get information about a specific container."""
    return await container_manager.get_container_info(container_id)


@app.delete("/containers/{container_id}", tags=["Containers"])
async def destroy_container(
    container_id: str = PathParam(...),
    _: bool = Depends(verify_api_key)
):
    """Destroy a container."""
    await container_manager.destroy_container(container_id)
    return {"message": f"Container {container_id} destroyed"}


@app.post("/containers/{container_id}/firewall", tags=["Containers"])
async def init_firewall(
    firewall_config: FirewallConfig,
    container_id: str = PathParam(...),
    _: bool = Depends(verify_api_key)
):
    """Initialize firewall for a container."""
    container = await container_manager.get_container(container_id)
    try:
        await container.init_firewall(allowed_domains=firewall_config.allowed_domains)
        return {"message": "Firewall initialized successfully"}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to initialize firewall: {str(e)}"
        )


# ==================== Code Execution Endpoints ====================

@app.post("/containers/{container_id}/execute", response_model=CodeExecutionResponse, tags=["Execution"])
async def execute_code(
    request: CodeExecutionRequest,
    container_id: str = PathParam(...),
    _: bool = Depends(verify_api_key)
):
    """Execute Python code in a container."""
    container = await container_manager.get_container(container_id)
    execution_id = str(uuid.uuid4())
    
    await container_manager.register_execution(container_id, execution_id)
    
    try:
        async with ExecutionClient(port=container.executor_port) as client:
            try:
                result = await client.execute(request.code, timeout=request.timeout)
                await container_manager.complete_execution(execution_id)
                
                return CodeExecutionResponse(
                    execution_id=execution_id,
                    text=result.text,
                    has_images=len(result.images) > 0,
                    completed=True
                )
            except ExecutionError as e:
                await container_manager.complete_execution(execution_id, error=str(e))
                return CodeExecutionResponse(
                    execution_id=execution_id,
                    error=str(e),
                    error_trace=e.trace,
                    completed=True
                )
            except asyncio.TimeoutError:
                await container_manager.complete_execution(execution_id, error="Execution timed out")
                return CodeExecutionResponse(
                    execution_id=execution_id,
                    error="Execution timed out",
                    completed=True
                )
    except Exception as e:
        await container_manager.complete_execution(execution_id, error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to execute code: {str(e)}"
        )


@app.post("/containers/{container_id}/execute/stream", tags=["Execution"])
async def execute_code_stream(
    request: CodeExecutionRequest,
    container_id: str = PathParam(...),
    _: bool = Depends(verify_api_key)
):
    """Execute Python code in a container with streaming output."""
    container = await container_manager.get_container(container_id)
    execution_id = str(uuid.uuid4())
    
    await container_manager.register_execution(container_id, execution_id)
    
    async def stream_generator():
        try:
            async with ExecutionClient(port=container.executor_port) as client:
                execution = await client.submit(request.code)
                
                try:
                    async for chunk in execution.stream(timeout=request.timeout):
                        yield f"data: {chunk}\n\n"
                    
                    # Send completion message
                    yield f"data: [DONE]\n\n"
                    await container_manager.complete_execution(execution_id)
                    
                except ExecutionError as e:
                    error_msg = {
                        "error": str(e),
                        "trace": e.trace
                    }
                    yield f"data: [ERROR] {str(error_msg)}\n\n"
                    await container_manager.complete_execution(execution_id, error=str(e))
                    
                except asyncio.TimeoutError:
                    yield f"data: [ERROR] Execution timed out\n\n"
                    await container_manager.complete_execution(execution_id, error="Execution timed out")
        
        except Exception as e:
            yield f"data: [ERROR] {str(e)}\n\n"
            await container_manager.complete_execution(execution_id, error=str(e))
    
    return StreamingResponse(
        stream_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Execution-ID": execution_id
        }
    )


@app.get("/executions/{execution_id}", response_model=ExecutionStatus, tags=["Execution"])
async def get_execution_status(
    execution_id: str = PathParam(...),
    _: bool = Depends(verify_api_key)
):
    """Get the status of a code execution."""
    return await container_manager.get_execution_status(execution_id)


# ==================== MCP Integration Endpoints ====================

@app.put("/containers/{container_id}/mcp/{server_name}", tags=["MCP"])
async def register_mcp_server(
    config: MCPServerConfig,
    container_id: str = PathParam(...),
    server_name: str = PathParam(...),
    relpath: str = Query("mcpgen"),
    _: bool = Depends(verify_api_key)
):
    """Register an MCP server for a container."""
    container = await container_manager.get_container(container_id)
    
    try:
        async with ResourceClient(port=container.resource_port) as client:
            tool_names = await client.generate_mcp_sources(
                relpath=relpath,
                server_name=server_name,
                server_params=config.server_params
            )
            return {"server_name": server_name, "tool_names": tool_names}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to register MCP server: {str(e)}"
        )


@app.get("/containers/{container_id}/mcp/{server_name}", tags=["MCP"])
async def get_mcp_server_tools(
    container_id: str = PathParam(...),
    server_name: str = PathParam(...),
    relpath: str = Query("mcpgen"),
    _: bool = Depends(verify_api_key)
):
    """Get available tools for an MCP server."""
    container = await container_manager.get_container(container_id)
    
    try:
        async with ResourceClient(port=container.resource_port) as client:
            sources = await client.get_mcp_sources(relpath=relpath, server_name=server_name)
            return {"server_name": server_name, "tools": list(sources.keys())}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get MCP server tools: {str(e)}"
        )


@app.post("/containers/{container_id}/mcp/{server_name}/{tool_name}", response_model=MCPToolResponse, tags=["MCP"])
async def execute_mcp_tool(
    request: MCPToolRequest,
    container_id: str = PathParam(...),
    server_name: str = PathParam(...),
    tool_name: str = PathParam(...),
    relpath: str = Query("mcpgen"),
    _: bool = Depends(verify_api_key)
):
    """Execute an MCP tool."""
    container = await container_manager.get_container(container_id)
    
    # First, ensure the client has access to the MCP sources
    try:
        async with ResourceClient(port=container.resource_port) as resource_client:
            sources = await resource_client.get_mcp_sources(relpath=relpath, server_name=server_name)
            if tool_name not in sources:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Tool {tool_name} not found in server {server_name}"
                )
        
        # Execute the code that calls the MCP tool
        async with ExecutionClient(port=container.executor_port) as exec_client:
            # Import the tool and execute it
            code = f"""
import json
from {relpath}.{server_name}.{tool_name} import Params, {tool_name}

params = Params(**{request.params})
result = {tool_name}(params)
print(json.dumps({{"result": result}}))
"""
            try:
                result = await exec_client.execute(code, timeout=request.timeout)
                if result.text:
                    try:
                        result_data = json.loads(result.text.strip())
                        return MCPToolResponse(result=result_data.get("result"))
                    except json.JSONDecodeError:
                        return MCPToolResponse(result=result.text)
                return MCPToolResponse(result=None)
            except ExecutionError as e:
                return MCPToolResponse(error=f"{str(e)}: {e.trace}")
            except asyncio.TimeoutError:
                return MCPToolResponse(error="Execution timed out")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to execute MCP tool: {str(e)}"
        )


# ==================== File Operations Endpoints ====================

@app.post("/containers/{container_id}/files/{relpath:path}", tags=["Files"])
async def upload_file(
    file: UploadFile = File(...),
    container_id: str = PathParam(...),
    relpath: str = PathParam(...),
    _: bool = Depends(verify_api_key)
):
    """Upload a file to a container."""
    container = await container_manager.get_container(container_id)
    
    try:
        async with ResourceClient(port=container.resource_port) as client:
            content = await file.read()
            await client.upload_file_content(relpath=f"{relpath}/{file.filename}", content=content)
            return {"message": f"File uploaded to {relpath}/{file.filename}"}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to upload file: {str(e)}"
        )


@app.get("/containers/{container_id}/files/{relpath:path}", tags=["Files"])
async def download_file(
    container_id: str = PathParam(...),
    relpath: str = PathParam(...),
    _: bool = Depends(verify_api_key)
):
    """Download a file from a container."""
    container = await container_manager.get_container(container_id)
    
    try:
        async with ResourceClient(port=container.resource_port) as client:
            content = await client.download_file_content(relpath=relpath)
            
            filename = Path(relpath).name
            
            return StreamingResponse(
                iter([content]),
                media_type="application/octet-stream",
                headers={"Content-Disposition": f"attachment; filename={filename}"}
            )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to download file: {str(e)}"
        )


@app.delete("/containers/{container_id}/files/{relpath:path}", tags=["Files"])
async def delete_file(
    container_id: str = PathParam(...),
    relpath: str = PathParam(...),
    _: bool = Depends(verify_api_key)
):
    """Delete a file from a container."""
    container = await container_manager.get_container(container_id)
    
    try:
        async with ResourceClient(port=container.resource_port) as client:
            await client.delete_file(relpath=relpath)
            return {"message": f"File {relpath} deleted"}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete file: {str(e)}"
        )


@app.post("/containers/{container_id}/directories/{relpath:path}", tags=["Files"])
async def upload_directory(
    file: UploadFile = File(...),
    container_id: str = PathParam(...),
    relpath: str = PathParam(...),
    _: bool = Depends(verify_api_key)
):
    """Upload a directory as a tar archive to a container."""
    container = await container_manager.get_container(container_id)
    
    if not file.filename.endswith((".tar", ".tar.gz", ".tgz")):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File must be a tar archive"
        )
    
    try:
        async with ResourceClient(port=container.resource_port) as client:
            content = await file.read()
            await client.upload_directory_content(relpath=relpath, content=content)
            return {"message": f"Directory uploaded to {relpath}"}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to upload directory: {str(e)}"
        )


@app.get("/containers/{container_id}/directories/{relpath:path}", tags=["Files"])
async def download_directory(
    container_id: str = PathParam(...),
    relpath: str = PathParam(...),
    _: bool = Depends(verify_api_key)
):
    """Download a directory as a tar archive from a container."""
    container = await container_manager.get_container(container_id)
    
    try:
        async with ResourceClient(port=container.resource_port) as client:
            content = await client.download_directory_content(relpath=relpath)
            
            dir_name = Path(relpath).name
            
            return StreamingResponse(
                iter([content]),
                media_type="application/x-gzip",
                headers={"Content-Disposition": f"attachment; filename={dir_name}.tar.gz"}
            )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to download directory: {str(e)}"
        )


if __name__ == "__main__":
    import uvicorn
    
    host = os.environ.get("IPYBOX_HOST", "0.0.0.0")
    port = int(os.environ.get("IPYBOX_PORT", "8000"))
    
    uvicorn.run(app, host=host, port=port)
