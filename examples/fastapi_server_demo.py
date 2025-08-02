#!/usr/bin/env python3
"""
ipybox FastAPI Server Demo

This script demonstrates how to use the ipybox FastAPI server API to:
1. Create and manage containers
2. Execute Python code (both regular and streaming)
3. Upload and download files
4. Set up MCP servers and execute tools
5. Manage container lifecycle

Usage:
    python fastapi_server_demo.py [--host HOST] [--port PORT] [--api-key API_KEY]
"""

import argparse
import asyncio
import io
import json
import os
import sys
import tarfile
from pathlib import Path
from typing import Any, Dict, List, Optional

import aiofiles
import aiohttp
from aiohttp import ClientSession, FormData


class IpyboxClient:
    """Client for interacting with the ipybox FastAPI server."""
    
    def __init__(self, host: str = "localhost", port: int = 8000, api_key: Optional[str] = None):
        self.base_url = f"http://{host}:{port}"
        self.headers = {"X-API-Key": api_key} if api_key else {}
        self.session = None
    
    async def __aenter__(self):
        self.session = aiohttp.ClientSession(headers=self.headers)
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
    
    # ==================== Container Management ====================
    
    async def create_container(self, tag: str = "gradion-ai/ipybox", binds: Dict[str, str] = None, 
                              env: Dict[str, str] = None) -> Dict[str, Any]:
        """Create a new execution container.
        
        Example HTTP Request:
        POST /containers
        {
            "tag": "gradion-ai/ipybox",
            "binds": {"./data": "data"},
            "env": {"MY_VAR": "value"}
        }
        """
        data = {
            "tag": tag,
            "binds": binds or {},
            "env": env or {},
            "show_pull_progress": False
        }
        
        async with self.session.post(f"{self.base_url}/containers", json=data) as response:
            if response.status != 200:
                error_text = await response.text()
                raise Exception(f"Failed to create container: {response.status} - {error_text}")
            
            return await response.json()
    
    async def list_containers(self) -> List[Dict[str, Any]]:
        """List all active containers.
        
        Example HTTP Request:
        GET /containers
        """
        async with self.session.get(f"{self.base_url}/containers") as response:
            if response.status != 200:
                error_text = await response.text()
                raise Exception(f"Failed to list containers: {response.status} - {error_text}")
            
            return await response.json()
    
    async def get_container_info(self, container_id: str) -> Dict[str, Any]:
        """Get information about a specific container.
        
        Example HTTP Request:
        GET /containers/{container_id}
        """
        async with self.session.get(f"{self.base_url}/containers/{container_id}") as response:
            if response.status != 200:
                error_text = await response.text()
                raise Exception(f"Failed to get container info: {response.status} - {error_text}")
            
            return await response.json()
    
    async def destroy_container(self, container_id: str) -> Dict[str, Any]:
        """Destroy a container.
        
        Example HTTP Request:
        DELETE /containers/{container_id}
        """
        async with self.session.delete(f"{self.base_url}/containers/{container_id}") as response:
            if response.status != 200:
                error_text = await response.text()
                raise Exception(f"Failed to destroy container: {response.status} - {error_text}")
            
            return await response.json()
    
    async def init_firewall(self, container_id: str, allowed_domains: List[str] = None) -> Dict[str, Any]:
        """Initialize firewall for a container.
        
        Example HTTP Request:
        POST /containers/{container_id}/firewall
        {
            "allowed_domains": ["pypi.org", "files.pythonhosted.org"]
        }
        """
        data = {"allowed_domains": allowed_domains or []}
        
        async with self.session.post(f"{self.base_url}/containers/{container_id}/firewall", json=data) as response:
            if response.status != 200:
                error_text = await response.text()
                raise Exception(f"Failed to initialize firewall: {response.status} - {error_text}")
            
            return await response.json()
    
    # ==================== Code Execution ====================
    
    async def execute_code(self, container_id: str, code: str, timeout: float = 120.0) -> Dict[str, Any]:
        """Execute Python code in a container.
        
        Example HTTP Request:
        POST /containers/{container_id}/execute
        {
            "code": "print('Hello, world!')",
            "timeout": 120.0
        }
        
        Example Response:
        {
            "execution_id": "uuid",
            "text": "Hello, world!",
            "has_images": false,
            "completed": true
        }
        """
        data = {"code": code, "timeout": timeout}
        
        async with self.session.post(f"{self.base_url}/containers/{container_id}/execute", json=data) as response:
            if response.status != 200:
                error_text = await response.text()
                raise Exception(f"Failed to execute code: {response.status} - {error_text}")
            
            return await response.json()
    
    async def execute_code_stream(self, container_id: str, code: str, timeout: float = 120.0):
        """Execute Python code in a container with streaming output.
        
        Example HTTP Request:
        POST /containers/{container_id}/execute/stream
        {
            "code": "for i in range(5): print(f'Count: {i}'); import time; time.sleep(0.5)",
            "timeout": 120.0
        }
        
        Example Response Stream:
        data: Count: 0
        
        data: Count: 1
        
        ...
        
        data: [DONE]
        """
        data = {"code": code, "timeout": timeout}
        
        async with self.session.post(f"{self.base_url}/containers/{container_id}/execute/stream", 
                                    json=data) as response:
            if response.status != 200:
                error_text = await response.text()
                raise Exception(f"Failed to execute code stream: {response.status} - {error_text}")
            
            # Get the execution ID from headers
            execution_id = response.headers.get("X-Execution-ID")
            
            # Process the event stream
            async for line in response.content:
                line = line.decode('utf-8').strip()
                if line.startswith("data:"):
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    elif data.startswith("[ERROR]"):
                        error_msg = data[7:].strip()
                        raise Exception(f"Execution error: {error_msg}")
                    else:
                        yield data
    
    async def get_execution_status(self, execution_id: str) -> Dict[str, Any]:
        """Get the status of a code execution.
        
        Example HTTP Request:
        GET /executions/{execution_id}
        
        Example Response:
        {
            "execution_id": "uuid",
            "container_id": "uuid",
            "status": "completed",
            "created_at": "2023-08-02T12:34:56.789Z",
            "completed_at": "2023-08-02T12:34:57.123Z",
            "error": null
        }
        """
        async with self.session.get(f"{self.base_url}/executions/{execution_id}") as response:
            if response.status != 200:
                error_text = await response.text()
                raise Exception(f"Failed to get execution status: {response.status} - {error_text}")
            
            return await response.json()
    
    # ==================== MCP Integration ====================
    
    async def register_mcp_server(self, container_id: str, server_name: str, 
                                 server_params: Dict[str, Any], relpath: str = "mcpgen") -> Dict[str, Any]:
        """Register an MCP server for a container.
        
        Example HTTP Request:
        PUT /containers/{container_id}/mcp/{server_name}?relpath=mcpgen
        {
            "server_params": {
                "command": "uvx",
                "args": ["mcp-server-fetch"]
            }
        }
        
        Example Response:
        {
            "server_name": "fetchurl",
            "tool_names": ["fetch"]
        }
        """
        data = {"server_params": server_params}
        
        async with self.session.put(
            f"{self.base_url}/containers/{container_id}/mcp/{server_name}?relpath={relpath}", 
            json=data
        ) as response:
            if response.status != 200:
                error_text = await response.text()
                raise Exception(f"Failed to register MCP server: {response.status} - {error_text}")
            
            return await response.json()
    
    async def get_mcp_server_tools(self, container_id: str, server_name: str, 
                                  relpath: str = "mcpgen") -> Dict[str, Any]:
        """Get available tools for an MCP server.
        
        Example HTTP Request:
        GET /containers/{container_id}/mcp/{server_name}?relpath=mcpgen
        
        Example Response:
        {
            "server_name": "fetchurl",
            "tools": ["fetch"]
        }
        """
        async with self.session.get(
            f"{self.base_url}/containers/{container_id}/mcp/{server_name}?relpath={relpath}"
        ) as response:
            if response.status != 200:
                error_text = await response.text()
                raise Exception(f"Failed to get MCP server tools: {response.status} - {error_text}")
            
            return await response.json()
    
    async def execute_mcp_tool(self, container_id: str, server_name: str, tool_name: str, 
                              params: Dict[str, Any], timeout: float = 5.0, 
                              relpath: str = "mcpgen") -> Dict[str, Any]:
        """Execute an MCP tool.
        
        Example HTTP Request:
        POST /containers/{container_id}/mcp/{server_name}/{tool_name}?relpath=mcpgen
        {
            "params": {"url": "https://example.com"},
            "timeout": 5.0
        }
        
        Example Response:
        {
            "result": "<!DOCTYPE html>...",
            "error": null
        }
        """
        data = {"params": params, "timeout": timeout}
        
        async with self.session.post(
            f"{self.base_url}/containers/{container_id}/mcp/{server_name}/{tool_name}?relpath={relpath}", 
            json=data
        ) as response:
            if response.status != 200:
                error_text = await response.text()
                raise Exception(f"Failed to execute MCP tool: {response.status} - {error_text}")
            
            return await response.json()
    
    # ==================== File Operations ====================
    
    async def upload_file(self, container_id: str, local_path: Path, remote_path: str) -> Dict[str, Any]:
        """Upload a file to a container.
        
        Example HTTP Request:
        POST /containers/{container_id}/files/{remote_path}
        Content-Type: multipart/form-data
        
        Example Response:
        {
            "message": "File uploaded to {remote_path}/{filename}"
        }
        """
        if not local_path.exists() or not local_path.is_file():
            raise FileNotFoundError(f"Local file not found: {local_path}")
        
        data = FormData()
        data.add_field('file', 
                      open(local_path, 'rb'),
                      filename=local_path.name)
        
        async with self.session.post(
            f"{self.base_url}/containers/{container_id}/files/{remote_path}", 
            data=data
        ) as response:
            if response.status != 200:
                error_text = await response.text()
                raise Exception(f"Failed to upload file: {response.status} - {error_text}")
            
            return await response.json()
    
    async def download_file(self, container_id: str, remote_path: str, local_path: Path) -> None:
        """Download a file from a container.
        
        Example HTTP Request:
        GET /containers/{container_id}/files/{remote_path}
        
        Example Response:
        [Binary file content with appropriate Content-Type]
        """
        # Create parent directories if needed
        local_path.parent.mkdir(parents=True, exist_ok=True)
        
        async with self.session.get(f"{self.base_url}/containers/{container_id}/files/{remote_path}") as response:
            if response.status != 200:
                error_text = await response.text()
                raise Exception(f"Failed to download file: {response.status} - {error_text}")
            
            # Stream content to file
            async with aiofiles.open(local_path, mode='wb') as f:
                await f.write(await response.read())
    
    async def delete_file(self, container_id: str, remote_path: str) -> Dict[str, Any]:
        """Delete a file from a container.
        
        Example HTTP Request:
        DELETE /containers/{container_id}/files/{remote_path}
        
        Example Response:
        {
            "message": "File {remote_path} deleted"
        }
        """
        async with self.session.delete(f"{self.base_url}/containers/{container_id}/files/{remote_path}") as response:
            if response.status != 200:
                error_text = await response.text()
                raise Exception(f"Failed to delete file: {response.status} - {error_text}")
            
            return await response.json()
    
    async def upload_directory(self, container_id: str, local_path: Path, remote_path: str) -> Dict[str, Any]:
        """Upload a directory as a tar archive to a container.
        
        Example HTTP Request:
        POST /containers/{container_id}/directories/{remote_path}
        Content-Type: multipart/form-data
        
        Example Response:
        {
            "message": "Directory uploaded to {remote_path}"
        }
        """
        if not local_path.exists() or not local_path.is_dir():
            raise FileNotFoundError(f"Local directory not found: {local_path}")
        
        # Create tar archive in memory
        tar_buffer = io.BytesIO()
        with tarfile.open(fileobj=tar_buffer, mode="w:gz") as tar:
            # Add directory contents to archive
            for item in local_path.rglob("*"):
                if item.is_file():
                    # Calculate relative path for archive
                    arcname = item.relative_to(local_path)
                    tar.add(item, arcname=str(arcname))
        
        # Reset buffer position
        tar_buffer.seek(0)
        
        # Create form data with the tar file
        data = FormData()
        data.add_field('file', 
                      tar_buffer.getvalue(),
                      filename=f"{local_path.name}.tar.gz",
                      content_type="application/x-gzip")
        
        async with self.session.post(
            f"{self.base_url}/containers/{container_id}/directories/{remote_path}", 
            data=data
        ) as response:
            if response.status != 200:
                error_text = await response.text()
                raise Exception(f"Failed to upload directory: {response.status} - {error_text}")
            
            return await response.json()
    
    async def download_directory(self, container_id: str, remote_path: str, local_path: Path) -> None:
        """Download a directory as a tar archive from a container.
        
        Example HTTP Request:
        GET /containers/{container_id}/directories/{remote_path}
        
        Example Response:
        [Binary tar.gz content with appropriate Content-Type]
        """
        # Create target directory
        local_path.mkdir(parents=True, exist_ok=True)
        
        async with self.session.get(f"{self.base_url}/containers/{container_id}/directories/{remote_path}") as response:
            if response.status != 200:
                error_text = await response.text()
                raise Exception(f"Failed to download directory: {response.status} - {error_text}")
            
            # Download tar content
            content = await response.read()
            
            # Extract tar archive
            with io.BytesIO(content) as tar_buffer:
                with tarfile.open(fileobj=tar_buffer, mode="r:gz") as tar:
                    # Extract all files
                    tar.extractall(path=local_path)


async def demo_container_management(client: IpyboxClient) -> str:
    """Demonstrate container management operations."""
    print("\n=== Container Management Demo ===")
    
    # Create a container
    print("\nCreating container...")
    container = await client.create_container()
    container_id = container["id"]
    print(f"Container created with ID: {container_id}")
    print(f"Executor port: {container['executor_port']}")
    print(f"Resource port: {container['resource_port']}")
    
    # Get container info
    print("\nGetting container info...")
    info = await client.get_container_info(container_id)
    print(f"Container status: {info['status']}")
    print(f"Created at: {info['created_at']}")
    
    # List all containers
    print("\nListing all containers...")
    containers = await client.list_containers()
    print(f"Total containers: {len(containers)}")
    
    # Initialize firewall
    print("\nInitializing firewall...")
    await client.init_firewall(container_id, ["pypi.org", "files.pythonhosted.org"])
    print("Firewall initialized")
    
    return container_id


async def demo_code_execution(client: IpyboxClient, container_id: str):
    """Demonstrate code execution."""
    print("\n=== Code Execution Demo ===")
    
    # Regular code execution
    print("\nExecuting simple code...")
    result = await client.execute_code(container_id, "print('Hello, world!')")
    print(f"Output: {result['text']}")
    
    # Code with variables
    print("\nExecuting code with variables...")
    result = await client.execute_code(container_id, """
x = 10
y = 20
print(f"Sum: {x + y}")
    """)
    print(f"Output: {result['text']}")
    
    # Code that generates an error
    print("\nExecuting code with error (handled)...")
    try:
        result = await client.execute_code(container_id, "print(undefined_variable)")
        print(f"Output: {result['text']}")
    except Exception as e:
        print(f"Caught error: {e}")
    
    # Streaming code execution
    print("\nExecuting streaming code...")
    code = """
import time
for i in range(5):
    print(f"Count: {i}")
    time.sleep(0.5)
print("Finished counting!")
    """
    
    print("Streaming output:")
    async for chunk in client.execute_code_stream(container_id, code):
        print(f"  Received: {chunk}")


async def demo_file_operations(client: IpyboxClient, container_id: str):
    """Demonstrate file operations."""
    print("\n=== File Operations Demo ===")
    
    # Create a temporary directory for the demo
    temp_dir = Path("./temp_demo")
    temp_dir.mkdir(exist_ok=True)
    
    # Create a test file
    test_file = temp_dir / "test.txt"
    async with aiofiles.open(test_file, "w") as f:
        await f.write("This is a test file for ipybox demo.")
    
    # Create a test directory with files
    test_subdir = temp_dir / "subdir"
    test_subdir.mkdir(exist_ok=True)
    async with aiofiles.open(test_subdir / "file1.txt", "w") as f:
        await f.write("This is file 1.")
    async with aiofiles.open(test_subdir / "file2.txt", "w") as f:
        await f.write("This is file 2.")
    
    # Upload a file
    print("\nUploading a file...")
    await client.upload_file(container_id, test_file, "demo")
    print(f"Uploaded {test_file} to container")
    
    # Execute code to verify the file exists
    print("\nVerifying file in container...")
    result = await client.execute_code(container_id, """
import os
print(f"File exists: {os.path.exists('/app/demo/test.txt')}")
with open('/app/demo/test.txt', 'r') as f:
    print(f"File content: {f.read()}")
    """)
    print(f"Output: {result['text']}")
    
    # Upload a directory
    print("\nUploading a directory...")
    await client.upload_directory(container_id, test_subdir, "demo/subdir")
    print(f"Uploaded {test_subdir} to container")
    
    # Execute code to verify the directory exists
    print("\nVerifying directory in container...")
    result = await client.execute_code(container_id, """
import os
print(f"Directory exists: {os.path.exists('/app/demo/subdir')}")
print("Files in directory:")
for file in os.listdir('/app/demo/subdir'):
    print(f"- {file}")
    """)
    print(f"Output: {result['text']}")
    
    # Create a file in the container
    print("\nCreating a file in the container...")
    result = await client.execute_code(container_id, """
with open('/app/demo/generated.txt', 'w') as f:
    f.write('This file was generated inside the container.')
print("File created")
    """)
    print(f"Output: {result['text']}")
    
    # Download the file
    print("\nDownloading the generated file...")
    download_path = temp_dir / "downloaded.txt"
    await client.download_file(container_id, "demo/generated.txt", download_path)
    print(f"Downloaded to {download_path}")
    
    # Show the content of the downloaded file
    async with aiofiles.open(download_path, "r") as f:
        content = await f.read()
    print(f"Downloaded file content: {content}")
    
    # Delete a file
    print("\nDeleting a file from the container...")
    await client.delete_file(container_id, "demo/test.txt")
    print("File deleted")
    
    # Verify the file is deleted
    result = await client.execute_code(container_id, """
import os
print(f"File exists: {os.path.exists('/app/demo/test.txt')}")
    """)
    print(f"Output: {result['text']}")
    
    # Clean up local temp directory
    for file in temp_dir.glob("**/*"):
        if file.is_file():
            file.unlink()
    for dir_path in sorted([d for d in temp_dir.glob("**/*") if d.is_dir()], reverse=True):
        dir_path.rmdir()
    temp_dir.rmdir()
    print("\nCleaned up local temporary files")


async def demo_mcp_integration(client: IpyboxClient, container_id: str):
    """Demonstrate MCP integration."""
    print("\n=== MCP Integration Demo ===")
    
    # Register an MCP server
    print("\nRegistering MCP server...")
    server_params = {
        "command": "python",
        "args": ["-c", """
import json
from mcp import StdioServer, ToolDefinition, TextContent

def fetch(url):
    import urllib.request
    with urllib.request.urlopen(url) as response:
        return response.read().decode('utf-8')

server = StdioServer()

@server.tool(
    name="fetch",
    description="Fetch content from a URL",
    parameters=[
        ToolDefinition.Parameter(
            name="url",
            type="string",
            description="URL to fetch",
            required=True
        )
    ]
)
def fetch_tool(params):
    try:
        content = fetch(params["url"])
        return TextContent(content)
    except Exception as e:
        return TextContent(f"Error: {str(e)}", is_error=True)

server.run()
"""]
    }
    
    try:
        result = await client.register_mcp_server(container_id, "fetchurl", server_params)
        print(f"MCP server registered with tools: {result['tool_names']}")
        
        # Get MCP server tools
        print("\nGetting MCP server tools...")
        tools = await client.get_mcp_server_tools(container_id, "fetchurl")
        print(f"Available tools: {tools['tools']}")
        
        # Execute MCP tool
        print("\nExecuting MCP tool...")
        tool_result = await client.execute_mcp_tool(
            container_id, "fetchurl", "fetch", {"url": "https://example.com"}, timeout=10.0
        )
        
        if tool_result.get("result"):
            # Show just the first 100 characters of the result
            print(f"Tool result (truncated): {tool_result['result'][:100]}...")
        else:
            print(f"Tool error: {tool_result.get('error')}")
        
        # Execute MCP tool directly in Python code
        print("\nExecuting MCP tool from Python code...")
        result = await client.execute_code(container_id, """
from mcpgen.fetchurl.fetch import Params, fetch
result = fetch(Params(url="https://example.com"))
print(f"Result length: {len(result)}")
print(result[:100] + "...")  # Show just the beginning
        """)
        print(f"Output: {result['text']}")
        
    except Exception as e:
        print(f"MCP demo failed: {e}")
        print("Skipping MCP integration demo")


async def main():
    parser = argparse.ArgumentParser(description="ipybox FastAPI Server Demo")
    parser.add_argument("--host", default="localhost", help="ipybox server host")
    parser.add_argument("--port", type=int, default=8000, help="ipybox server port")
    parser.add_argument("--api-key", help="API key for authentication")
    args = parser.parse_args()
    
    print(f"Connecting to ipybox server at {args.host}:{args.port}")
    if args.api_key:
        print("Using API key authentication")
    else:
        print("No API key provided, authentication disabled")
    
    try:
        async with IpyboxClient(args.host, args.port, args.api_key) as client:
            # Check server health
            try:
                async with client.session.get(f"{client.base_url}/health") as response:
                    if response.status == 200:
                        health = await response.json()
                        print(f"Server health: {health['status']}")
                    else:
                        print(f"Server health check failed: {response.status}")
                        return
            except Exception as e:
                print(f"Failed to connect to server: {e}")
                return
            
            # Run the demos
            try:
                container_id = await demo_container_management(client)
                await demo_code_execution(client, container_id)
                await demo_file_operations(client, container_id)
                await demo_mcp_integration(client, container_id)
                
                # Clean up
                print("\n=== Cleanup ===")
                print("Destroying container...")
                await client.destroy_container(container_id)
                print(f"Container {container_id} destroyed")
                
            except Exception as e:
                print(f"Demo failed: {e}")
    
    except Exception as e:
        print(f"Client error: {e}")


if __name__ == "__main__":
    asyncio.run(main())
