import asyncio

from ipybox import ExecutionClient, ExecutionContainer


async def main():
    tag = "ghcr.io/gradion-ai/ipybox:minimal"  # (1)!
    async with ExecutionContainer(tag) as container:  # (2)!
        async with ExecutionClient(port=container.executor_port) as client:  # (3)!
            result = await client.execute("print('Hello, world!')")  # (4)!
            print(f"Output: {result.text}")  # (5)!


if __name__ == "__main__":
    asyncio.run(main())
