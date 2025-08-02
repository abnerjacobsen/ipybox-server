"""
MCP (Model Context Protocol) Proxy Implementation

This module provides a proxy implementation for the Model Context Protocol (MCP),
allowing HTTP clients to communicate with stdio-based MCP servers running in containers.
It implements the Streamable HTTP transport as specified in the MCP specification.

References:
- MCP Specification: https://modelcontextprotocol.io/specification/
- JSON-RPC 2.0: https://www.jsonrpc.org/specification
"""

import asyncio
import json
import logging
import os
import re
import shlex
import subprocess
import time
import uuid
from asyncio import create_subprocess_exec, create_subprocess_shell
from asyncio.subprocess import PIPE
from contextlib import asynccontextmanager
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Union, AsyncGenerator

import aiofiles
from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

# Configure logging
logger = logging.getLogger("ipybox.mcp_proxy")

# Define JSON-RPC 2.0 models
class JSONRPC20Request(BaseModel):
    """JSON-RPC 2.0 request model"""
    jsonrpc: str = Field("2.0", description="JSON-RPC version, must be 2.0")
    method: str = Field(..., description="Method name")
    params: Optional[Union[Dict[str, Any], List[Any]]] = Field(None, description="Method parameters")
    id: Optional[Union[str, int]] = Field(None, description="Request ID")

class JSONRPC20Response(BaseModel):
    """JSON-RPC 2.0 response model"""
    jsonrpc: str = Field("2.0", description="JSON-RPC version, must be 2.0")
    result: Optional[Any] = Field(None, description="Result of the method call")
    error: Optional[Dict[str, Any]] = Field(None, description="Error information")
    id: Optional[Union[str, int]] = Field(None, description="Request ID")

class JSONRPC20Error(BaseModel):
    """JSON-RPC 2.0 error model"""
    code: int = Field(..., description="Error code")
    message: str = Field(..., description="Error message")
    data: Optional[Any] = Field(None, description="Additional error data")

class MCPSessionState(str, Enum):
    """MCP session state enum"""
    INITIALIZING = "initializing"
    ACTIVE = "active"
    CLOSING = "closing"
    CLOSED = "closed"
    ERROR = "error"

class MCPSession:
    """
    Manages an individual MCP session with a stdio-based MCP server.
    
    Each session corresponds to a single client connection and manages
    the lifecycle of the MCP server subprocess.
    """
    def __init__(
        self,
        session_id: str,
        container_id: str,
        server_name: str,
        command: str,
        args: List[str],
        working_dir: Optional[str] = None,
        env: Optional[Dict[str, str]] = None,
        timeout: int = 60,
    ):
        self.session_id = session_id
        self.container_id = container_id
        self.server_name = server_name
        self.command = command
        self.args = args
        self.working_dir = working_dir
        self.env = env or {}
        self.timeout = timeout
        self.state = MCPSessionState.INITIALIZING
        self.process = None
        self.last_activity = time.time()
        self.initialized = False
        self.capabilities = {}
        self.protocol_version = None
        self._stdin_queue = asyncio.Queue()
        self._stdout_queue = asyncio.Queue()
        self._tasks = []

    async def start(self):
        """Start the MCP server subprocess and initialize communication tasks"""
        try:
            # Prepare the command to execute in the container
            cmd = [self.command] + self.args
            cmd_str = " ".join(shlex.quote(arg) for arg in cmd)
            
            logger.info(f"Starting MCP server in container {self.container_id}: {cmd_str}")
            
            # Create the subprocess
            self.process = await create_subprocess_exec(
                *cmd,
                stdin=PIPE,
                stdout=PIPE,
                stderr=PIPE,
                cwd=self.working_dir,
                env={**os.environ, **self.env}
            )
            
            # Start communication tasks
            self._tasks = [
                asyncio.create_task(self._read_stdout()),
                asyncio.create_task(self._read_stderr()),
                asyncio.create_task(self._write_stdin()),
            ]
            
            self.state = MCPSessionState.ACTIVE
            self.last_activity = time.time()
            logger.info(f"MCP session {self.session_id} started successfully")
            return True
        except Exception as e:
            logger.error(f"Failed to start MCP session {self.session_id}: {str(e)}")
            self.state = MCPSessionState.ERROR
            return False

    async def stop(self):
        """Stop the MCP server subprocess and clean up resources"""
        if self.state in (MCPSessionState.CLOSED, MCPSessionState.CLOSING):
            return
        
        self.state = MCPSessionState.CLOSING
        logger.info(f"Stopping MCP session {self.session_id}")
        
        # Cancel all tasks
        for task in self._tasks:
            if not task.done():
                task.cancel()
        
        # Terminate the process if it's still running
        if self.process and self.process.returncode is None:
            try:
                self.process.terminate()
                await asyncio.wait_for(self.process.wait(), timeout=2.0)
            except asyncio.TimeoutError:
                logger.warning(f"MCP process did not terminate gracefully, killing it")
                self.process.kill()
                await self.process.wait()
            except Exception as e:
                logger.error(f"Error stopping MCP process: {str(e)}")
        
        self.state = MCPSessionState.CLOSED
        logger.info(f"MCP session {self.session_id} stopped")

    async def send_message(self, message: Dict[str, Any]) -> None:
        """Send a JSON-RPC message to the MCP server"""
        if self.state != MCPSessionState.ACTIVE:
            raise RuntimeError(f"Cannot send message to MCP server in state {self.state}")
        
        self.last_activity = time.time()
        message_str = json.dumps(message) + "\n"
        await self._stdin_queue.put(message_str)
        logger.debug(f"Queued message to MCP server: {message_str.strip()}")

    async def receive_message(self, timeout: Optional[float] = None) -> Dict[str, Any]:
        """Receive a JSON-RPC message from the MCP server"""
        if self.state != MCPSessionState.ACTIVE:
            raise RuntimeError(f"Cannot receive message from MCP server in state {self.state}")
        
        try:
            if timeout:
                message_str = await asyncio.wait_for(self._stdout_queue.get(), timeout=timeout)
            else:
                message_str = await self._stdout_queue.get()
            
            self.last_activity = time.time()
            message = json.loads(message_str)
            logger.debug(f"Received message from MCP server: {message}")
            return message
        except asyncio.TimeoutError:
            logger.warning(f"Timeout waiting for message from MCP server")
            raise
        except json.JSONDecodeError as e:
            logger.error(f"Failed to decode JSON from MCP server: {str(e)}")
            raise

    async def _read_stdout(self):
        """Read stdout from the MCP server subprocess"""
        assert self.process is not None
        
        try:
            while True:
                line = await self.process.stdout.readline()
                if not line:
                    break
                
                line_str = line.decode("utf-8").strip()
                if line_str:
                    logger.debug(f"MCP stdout: {line_str}")
                    await self._stdout_queue.put(line_str)
        except asyncio.CancelledError:
            logger.debug("_read_stdout task cancelled")
            raise
        except Exception as e:
            logger.error(f"Error reading from MCP stdout: {str(e)}")
        finally:
            logger.debug("_read_stdout task finished")

    async def _read_stderr(self):
        """Read stderr from the MCP server subprocess"""
        assert self.process is not None
        
        try:
            while True:
                line = await self.process.stderr.readline()
                if not line:
                    break
                
                line_str = line.decode("utf-8").strip()
                if line_str:
                    logger.debug(f"MCP stderr: {line_str}")
        except asyncio.CancelledError:
            logger.debug("_read_stderr task cancelled")
            raise
        except Exception as e:
            logger.error(f"Error reading from MCP stderr: {str(e)}")
        finally:
            logger.debug("_read_stderr task finished")

    async def _write_stdin(self):
        """Write to stdin of the MCP server subprocess"""
        assert self.process is not None
        
        try:
            while True:
                message = await self._stdin_queue.get()
                if not message:
                    break
                
                self.process.stdin.write(message.encode("utf-8"))
                await self.process.stdin.drain()
                self._stdin_queue.task_done()
        except asyncio.CancelledError:
            logger.debug("_write_stdin task cancelled")
            raise
        except Exception as e:
            logger.error(f"Error writing to MCP stdin: {str(e)}")
        finally:
            logger.debug("_write_stdin task finished")

    def is_idle_timeout(self, max_idle_time: int) -> bool:
        """Check if the session has exceeded the idle timeout"""
        return time.time() - self.last_activity > max_idle_time

class MCPProxy:
    """
    MCP Proxy that bridges HTTP clients with stdio-based MCP servers.
    
    This class manages MCP sessions and handles the translation between
    HTTP requests/responses and stdio-based MCP communication.
    """
    def __init__(
        self,
        container_manager,
        session_timeout: int = 3600,
        cleanup_interval: int = 300,
    ):
        self.container_manager = container_manager
        self.session_timeout = session_timeout
        self.cleanup_interval = cleanup_interval
        self.sessions: Dict[str, MCPSession] = {}
        self._cleanup_task = None
        
    async def start(self):
        """Start the MCP proxy and the cleanup task"""
        self._cleanup_task = asyncio.create_task(self._cleanup_idle_sessions())
        logger.info("MCP proxy started")
    
    async def stop(self):
        """Stop the MCP proxy and all active sessions"""
        logger.info("Stopping MCP proxy")
        
        # Cancel the cleanup task
        if self._cleanup_task and not self._cleanup_task.done():
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
        
        # Stop all sessions
        tasks = []
        for session_id, session in list(self.sessions.items()):
            tasks.append(asyncio.create_task(session.stop()))
        
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        
        self.sessions.clear()
        logger.info("MCP proxy stopped")
    
    async def _cleanup_idle_sessions(self):
        """Periodically clean up idle sessions"""
        try:
            while True:
                await asyncio.sleep(self.cleanup_interval)
                
                # Find idle sessions
                idle_sessions = []
                for session_id, session in list(self.sessions.items()):
                    if session.is_idle_timeout(self.session_timeout):
                        idle_sessions.append(session_id)
                
                # Stop and remove idle sessions
                for session_id in idle_sessions:
                    logger.info(f"Cleaning up idle MCP session {session_id}")
                    session = self.sessions.pop(session_id, None)
                    if session:
                        await session.stop()
        except asyncio.CancelledError:
            logger.debug("Cleanup task cancelled")
            raise
        except Exception as e:
            logger.error(f"Error in cleanup task: {str(e)}")
    
    async def get_or_create_session(
        self,
        container_id: str,
        server_name: str,
        session_id: Optional[str] = None,
        command: Optional[str] = None,
        args: Optional[List[str]] = None,
        working_dir: Optional[str] = None,
        env: Optional[Dict[str, str]] = None,
    ) -> Tuple[str, MCPSession]:
        """
        Get an existing session or create a new one
        
        Returns a tuple of (session_id, session)
        """
        # If session_id is provided and exists, return it
        if session_id and session_id in self.sessions:
            session = self.sessions[session_id]
            if session.container_id == container_id and session.server_name == server_name:
                session.last_activity = time.time()
                return session_id, session
        
        # Create a new session
        new_session_id = session_id or f"mcp-{uuid.uuid4()}"
        
        # Use default command/args if not provided
        if command is None:
            command = "uvx"  # Default command for supergateway
        
        if args is None:
            # Default args to run supergateway as a bridge
            args = ["supergateway", "--stdio", f"mcp-server-{server_name}"]
        
        # Create and start the session
        session = MCPSession(
            session_id=new_session_id,
            container_id=container_id,
            server_name=server_name,
            command=command,
            args=args,
            working_dir=working_dir,
            env=env,
            timeout=self.session_timeout,
        )
        
        success = await session.start()
        if not success:
            raise HTTPException(status_code=500, detail=f"Failed to start MCP session for server {server_name}")
        
        self.sessions[new_session_id] = session
        return new_session_id, session
    
    async def handle_mcp_request(
        self,
        container_id: str,
        server_name: str,
        request_data: Dict[str, Any],
        session_id: Optional[str] = None,
        command: Optional[str] = None,
        args: Optional[List[str]] = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Handle an MCP request and yield responses
        
        This is a generator that yields JSON-RPC responses from the MCP server.
        It handles session creation/retrieval and message passing.
        """
        # Get or create the session
        try:
            session_id, session = await self.get_or_create_session(
                container_id=container_id,
                server_name=server_name,
                session_id=session_id,
                command=command,
                args=args,
            )
        except Exception as e:
            error_response = {
                "jsonrpc": "2.0",
                "error": {
                    "code": -32603,
                    "message": f"Internal error: {str(e)}",
                },
                "id": request_data.get("id")
            }
            yield error_response
            return
        
        # Send the request to the MCP server
        try:
            await session.send_message(request_data)
            
            # Handle initialize method specially to set up the session
            if request_data.get("method") == "initialize":
                session.initialized = True
            
            # Wait for and yield responses
            # For initialize, we expect exactly one response
            # For other methods, we may get multiple responses before the final one
            request_id = request_data.get("id")
            is_notification = request_id is None
            
            if is_notification:
                # For notifications, we don't expect a response
                return
            
            while True:
                try:
                    response = await session.receive_message(timeout=30.0)
                    
                    # Yield the response
                    yield response
                    
                    # If this response matches our request ID, we're done
                    if "id" in response and response["id"] == request_id:
                        break
                    
                except asyncio.TimeoutError:
                    # If we timeout waiting for a response, return an error
                    error_response = {
                        "jsonrpc": "2.0",
                        "error": {
                            "code": -32603,
                            "message": "Timeout waiting for response from MCP server",
                        },
                        "id": request_id
                    }
                    yield error_response
                    break
        except Exception as e:
            logger.error(f"Error handling MCP request: {str(e)}")
            error_response = {
                "jsonrpc": "2.0",
                "error": {
                    "code": -32603,
                    "message": f"Internal error: {str(e)}",
                },
                "id": request_data.get("id")
            }
            yield error_response
    
    def create_router(self) -> APIRouter:
        """Create a FastAPI router with MCP endpoints"""
        router = APIRouter()
        
        @router.post("/containers/{container_id}/mcp-proxy/{server_name}")
        async def mcp_proxy_endpoint(
            container_id: str,
            server_name: str,
            request: Request,
            response: Response,
            mcp_session_id: Optional[str] = Header(None),
        ):
            # Check if the container exists
            container = await self.container_manager.get_container(container_id)
            if not container:
                raise HTTPException(status_code=404, detail=f"Container {container_id} not found")
            
            # Parse the request body as JSON
            try:
                request_data = await request.json()
            except json.JSONDecodeError:
                return JSONResponse(
                    status_code=400,
                    content={
                        "jsonrpc": "2.0",
                        "error": {
                            "code": -32700,
                            "message": "Parse error: Invalid JSON"
                        },
                        "id": None
                    }
                )
            
            # Validate JSON-RPC request
            try:
                if isinstance(request_data, list):
                    # Batch request
                    for item in request_data:
                        JSONRPC20Request(**item)
                else:
                    # Single request
                    JSONRPC20Request(**request_data)
            except Exception as e:
                return JSONResponse(
                    status_code=400,
                    content={
                        "jsonrpc": "2.0",
                        "error": {
                            "code": -32600,
                            "message": f"Invalid Request: {str(e)}"
                        },
                        "id": request_data.get("id") if isinstance(request_data, dict) else None
                    }
                )
            
            # Check Accept header to determine response format
            accept_header = request.headers.get("accept", "application/json")
            use_sse = "text/event-stream" in accept_header
            
            # Handle the request based on response format
            if use_sse:
                # Use SSE for streaming responses
                async def event_stream():
                    async for response in self.handle_mcp_request(
                        container_id=container_id,
                        server_name=server_name,
                        request_data=request_data,
                        session_id=mcp_session_id,
                    ):
                        # Format as SSE event
                        data = json.dumps(response)
                        yield f"data: {data}\n\n"
                
                # Set session ID header if available
                headers = {}
                if mcp_session_id:
                    headers["Mcp-Session-Id"] = mcp_session_id
                
                return StreamingResponse(
                    event_stream(),
                    media_type="text/event-stream",
                    headers=headers
                )
            else:
                # Use JSON for non-streaming responses
                responses = []
                async for response in self.handle_mcp_request(
                    container_id=container_id,
                    server_name=server_name,
                    request_data=request_data,
                    session_id=mcp_session_id,
                ):
                    responses.append(response)
                
                # Set session ID header if available
                headers = {}
                if mcp_session_id:
                    headers["Mcp-Session-Id"] = mcp_session_id
                
                # For batch requests, return array of responses
                # For single requests, return single response
                if isinstance(request_data, list):
                    return JSONResponse(content=responses, headers=headers)
                else:
                    return JSONResponse(content=responses[0] if responses else None, headers=headers)
        
        return router

# Factory function to create MCP proxy instance
def create_mcp_proxy(container_manager, session_timeout=3600, cleanup_interval=300):
    """Create and initialize an MCP proxy instance"""
    proxy = MCPProxy(
        container_manager=container_manager,
        session_timeout=session_timeout,
        cleanup_interval=cleanup_interval,
    )
    return proxy

# Context manager for MCP proxy lifecycle
@asynccontextmanager
async def mcp_proxy_lifecycle(container_manager, session_timeout=3600, cleanup_interval=300):
    """Context manager for MCP proxy lifecycle"""
    proxy = create_mcp_proxy(
        container_manager=container_manager,
        session_timeout=session_timeout,
        cleanup_interval=cleanup_interval,
    )
    await proxy.start()
    try:
        yield proxy
    finally:
        await proxy.stop()
