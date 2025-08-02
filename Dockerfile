# Multi-stage Dockerfile for ipybox FastAPI Server
# Supports both development and production environments

# -----------------------------------------------------------------------------
# Base image with common dependencies
# -----------------------------------------------------------------------------
FROM python:3.11-slim AS base

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONFAULTHANDLER=1 \
    PIP_NO_CACHE_DIR=off \
    PIP_DISABLE_PIP_VERSION_CHECK=on \
    PIP_DEFAULT_TIMEOUT=100 \
    POETRY_VERSION=1.7.1 \
    IPYBOX_HOST=0.0.0.0 \
    IPYBOX_PORT=8000

# Create non-root user for security
RUN groupadd -g 1000 ipybox && \
    useradd -u 1000 -g ipybox -s /bin/bash -m ipybox

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    gnupg \
    lsb-release \
    ca-certificates \
    apt-transport-https \
    software-properties-common \
    && rm -rf /var/lib/apt/lists/*

# Install Docker CLI
RUN curl -fsSL https://download.docker.com/linux/debian/gpg | gpg --dearmor -o /usr/share/keyrings/docker-archive-keyring.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/docker-archive-keyring.gpg] https://download.docker.com/linux/debian \
    $(lsb_release -cs) stable" | tee /etc/apt/sources.list.d/docker.list > /dev/null \
    && apt-get update && apt-get install -y --no-install-recommends docker-ce-cli \
    && rm -rf /var/lib/apt/lists/*

# Create app directory
WORKDIR /app

# -----------------------------------------------------------------------------
# Dependencies stage
# -----------------------------------------------------------------------------
FROM base AS deps

# Install Python dependencies
RUN pip install --upgrade pip setuptools wheel uv

# Copy dependency files
COPY pyproject.toml ./
COPY uv.lock ./

# Install production dependencies
RUN uv pip install --system -e .

# -----------------------------------------------------------------------------
# Development stage
# -----------------------------------------------------------------------------
FROM deps AS development

# Install development dependencies
RUN uv pip install --system -e ".[dev]"

# Add docker group to ipybox user for socket access
RUN groupadd -g 999 docker-external \
    && usermod -aG docker-external ipybox

# Copy application code
COPY --chown=ipybox:ipybox . .

# Set permissions for Docker socket access
RUN chmod 666 /var/run/docker.sock || true

# Switch to non-root user
USER ipybox

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Default command for development with hot reload
CMD ["python", "run_server.py", "--dev", "--log-level", "DEBUG"]

# -----------------------------------------------------------------------------
# Production stage
# -----------------------------------------------------------------------------
FROM base AS production

# Copy installed dependencies from deps stage
COPY --from=deps /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=deps /usr/local/bin /usr/local/bin

# Copy application code
COPY --chown=ipybox:ipybox . .

# Add docker group to ipybox user for socket access
RUN groupadd -g 999 docker-external \
    && usermod -aG docker-external ipybox

# Set permissions for Docker socket access
RUN chmod 666 /var/run/docker.sock || true

# Switch to non-root user
USER ipybox

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Default command for production
CMD ["python", "run_server.py"]

# Build with:
# For development: docker build --target development -t ipybox-server:dev .
# For production: docker build --target production -t ipybox-server:prod .
