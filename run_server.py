#!/usr/bin/env python3
"""
ipybox FastAPI Server

This script starts the ipybox FastAPI server with proper configuration.
It provides a secure Python code execution sandbox based on IPython and Docker.

Usage:
    python run_server.py [options]

Environment Variables:
    IPYBOX_HOST - Host to bind the server to (default: 0.0.0.0)
    IPYBOX_PORT - Port to bind the server to (default: 8000)
    IPYBOX_API_KEY - API key for authentication (default: none, auth disabled)
    IPYBOX_DEFAULT_TAG - Default Docker image tag (default: gradion-ai/ipybox)
    IPYBOX_CLEANUP_INTERVAL - Interval in seconds for container cleanup (default: 300)
    IPYBOX_MAX_IDLE_TIME - Maximum idle time in seconds for containers (default: 3600)
    IPYBOX_CORS_ORIGINS - Comma-separated list of allowed CORS origins (default: *)
    IPYBOX_LOG_LEVEL - Logging level (default: INFO)
"""

import argparse
import asyncio
import logging
import os
import signal
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import List, Optional

try:
    import uvicorn
    from dotenv import load_dotenv
except ImportError:
    print("Required packages not installed. Install with:")
    print("pip install uvicorn[standard] python-dotenv")
    sys.exit(1)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("ipybox.server")


def check_docker_available() -> bool:
    """Check if Docker is available and running."""
    try:
        result = subprocess.run(
            ["docker", "info"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        return result.returncode == 0
    except FileNotFoundError:
        return False


def print_api_examples(host: str, port: int, api_key: Optional[str] = None):
    """Print example API usage commands."""
    base_url = f"http://{host}:{port}"
    auth_header = f'-H "X-API-Key: {api_key}"' if api_key else ""

    examples = [
        ("Health check", f"curl {base_url}/health"),
        ("Create container", f'curl -X POST {base_url}/containers {auth_header} -H "Content-Type: application/json" -d \'{{"tag": "gradion-ai/ipybox"}}\''),
        ("List containers", f"curl {base_url}/containers {auth_header}"),
        ("Execute code", f'curl -X POST {base_url}/containers/{{container_id}}/execute {auth_header} -H "Content-Type: application/json" -d \'{{"code": "print(\\\"Hello, world!\\\")"}}\''),
        ("Stream code execution", f'curl -X POST {base_url}/containers/{{container_id}}/execute/stream {auth_header} -H "Content-Type: application/json" -d \'{{"code": "for i in range(5): print(f\\\"Count: {{i}}\\\"); import time; time.sleep(0.5)"}}\''),
        ("Upload file", f"curl -X POST {base_url}/containers/{{container_id}}/files/{{path}} {auth_header} -F 'file=@local_file.txt'"),
        ("Download file", f"curl {base_url}/containers/{{container_id}}/files/{{path}} {auth_header} -o downloaded_file.txt"),
        ("Register MCP server", f'curl -X PUT {base_url}/containers/{{container_id}}/mcp/{{server_name}} {auth_header} -H "Content-Type: application/json" -d \'{{"server_params": {{"command": "python", "args": ["-m", "my_mcp_server"]}}}}\''),
        ("Execute MCP tool", f'curl -X POST {base_url}/containers/{{container_id}}/mcp/{{server_name}}/{{tool_name}} {auth_header} -H "Content-Type: application/json" -d \'{{"params": {{"param1": "value1"}}}}\''),
    ]

    print("\nAPI Usage Examples:")
    print("===================")
    
    for title, command in examples:
        print(f"\n{title}:")
        print(textwrap.fill(command, width=100, subsequent_indent="  "))


def print_configuration(args):
    """Print server configuration."""
    print("\nipybox Server Configuration:")
    print("===========================")
    print(f"Host:              {args.host}")
    print(f"Port:              {args.port}")
    print(f"API Key:           {'Enabled' if args.api_key else 'Disabled'}")
    print(f"Default Docker tag: {args.default_tag}")
    print(f"Container cleanup interval: {args.cleanup_interval} seconds")
    print(f"Container max idle time:    {args.max_idle_time} seconds")
    print(f"CORS origins:      {args.cors_origins}")
    print(f"Log level:         {args.log_level}")
    print(f"Development mode:  {'Enabled' if args.dev else 'Disabled'}")
    print("===========================\n")


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="Start the ipybox FastAPI server")
    
    parser.add_argument("--host", default=os.environ.get("IPYBOX_HOST", "0.0.0.0"),
                        help="Host to bind the server to (default: 0.0.0.0)")
    
    parser.add_argument("--port", type=int, default=int(os.environ.get("IPYBOX_PORT", "8000")),
                        help="Port to bind the server to (default: 8000)")
    
    parser.add_argument("--api-key", default=os.environ.get("IPYBOX_API_KEY", ""),
                        help="API key for authentication (default: none, auth disabled)")
    
    parser.add_argument("--default-tag", default=os.environ.get("IPYBOX_DEFAULT_TAG", "gradion-ai/ipybox"),
                        help="Default Docker image tag (default: gradion-ai/ipybox)")
    
    parser.add_argument("--cleanup-interval", type=int, 
                        default=int(os.environ.get("IPYBOX_CLEANUP_INTERVAL", "300")),
                        help="Interval in seconds for container cleanup (default: 300)")
    
    parser.add_argument("--max-idle-time", type=int,
                        default=int(os.environ.get("IPYBOX_MAX_IDLE_TIME", "3600")),
                        help="Maximum idle time in seconds for containers (default: 3600)")
    
    parser.add_argument("--cors-origins", default=os.environ.get("IPYBOX_CORS_ORIGINS", "*"),
                        help="Comma-separated list of allowed CORS origins (default: *)")
    
    parser.add_argument("--log-level", default=os.environ.get("IPYBOX_LOG_LEVEL", "INFO"),
                        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
                        help="Logging level (default: INFO)")
    
    parser.add_argument("--dev", action="store_true",
                        help="Enable development mode with hot reload")
    
    parser.add_argument("--examples", action="store_true",
                        help="Show API usage examples and exit")
    
    parser.add_argument("--env-file", type=str, default=".env",
                        help="Path to .env file for loading environment variables")
    
    return parser.parse_args()


def setup_environment(args):
    """Set up environment variables for the server."""
    os.environ["IPYBOX_HOST"] = args.host
    os.environ["IPYBOX_PORT"] = str(args.port)
    os.environ["IPYBOX_API_KEY"] = args.api_key
    os.environ["IPYBOX_DEFAULT_TAG"] = args.default_tag
    os.environ["IPYBOX_CLEANUP_INTERVAL"] = str(args.cleanup_interval)
    os.environ["IPYBOX_MAX_IDLE_TIME"] = str(args.max_idle_time)
    os.environ["IPYBOX_CORS_ORIGINS"] = args.cors_origins
    
    # Configure logging level
    numeric_level = getattr(logging, args.log_level.upper(), None)
    if isinstance(numeric_level, int):
        logging.root.setLevel(numeric_level)


def main():
    """Main entry point for the server."""
    # Load environment variables from .env file if it exists
    env_path = Path(".env")
    if env_path.exists():
        load_dotenv(env_path)
    
    # Parse command line arguments
    args = parse_args()
    
    # Load environment variables from specified env file if provided
    if args.env_file and Path(args.env_file).exists():
        load_dotenv(args.env_file, override=True)
        # Re-parse args to allow env file to override defaults
        args = parse_args()
    
    # Set up environment variables
    setup_environment(args)
    
    # Show API examples if requested
    if args.examples:
        print_api_examples(args.host, args.port, args.api_key)
        return 0
    
    # Print configuration
    print_configuration(args)
    
    # Check if Docker is available
    if not check_docker_available():
        logger.error("Docker is not available or not running. Please install Docker and ensure it's running.")
        return 1
    
    # Import server module here to ensure environment variables are set
    from ipybox.server import app
    
    # Set up signal handlers for graceful shutdown
    def handle_exit_signal(sig, frame):
        logger.info(f"Received exit signal {sig}. Shutting down...")
        sys.exit(0)
    
    signal.signal(signal.SIGINT, handle_exit_signal)
    signal.signal(signal.SIGTERM, handle_exit_signal)
    
    # Start the server
    logger.info(f"Starting ipybox server on {args.host}:{args.port}")
    uvicorn.run(
        "ipybox.server:app",
        host=args.host,
        port=args.port,
        reload=args.dev,
        log_level=args.log_level.lower(),
    )
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
