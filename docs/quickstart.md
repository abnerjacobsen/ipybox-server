# Quickstart

Install `ipybox` with:

```bash
pip install ipybox
```

Execute Python code in an `ipybox` container:

```python
--8<-- "examples/00_quickstart.py"
```

1. Name and tag of a [prebuilt](https://gradion-ai.github.io/freeact/environment/#prebuilt-docker-images) `ipybox` Docker image.
2. Create and start a code execution container and remove it on context manager exit.
3. Create an IPython kernel in the container and remove it on context manager exit.
4. Execute Python code in the kernel and await the result.
5. Prints: `Output: Hello, world!`
