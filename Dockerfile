FROM python:3.12-slim

WORKDIR /app

# Copy pyproject.toml for dependency installation
COPY pyproject.toml .

# Install dependencies
RUN pip install --no-cache-dir .

# Copy application code
COPY src/ ./src/

# Environment variables
ENV PYTHONUNBUFFERED=1

# Port is configured at runtime via MCP_SERVER_PORT env var

# Run the server
CMD ["python", "-m", "src.main"]