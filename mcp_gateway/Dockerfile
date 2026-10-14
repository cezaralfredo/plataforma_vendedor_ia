# =============================================================================
# MCP Gateway - Lightweight proxy for Hermes -> API MCP communication
# =============================================================================

FROM python:3.12-slim AS builder

WORKDIR /app

RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir uv

COPY requirements.txt .
RUN uv pip install --system --no-cache -r requirements.txt

# =============================================================================
# Runtime stage
# =============================================================================

FROM python:3.12-slim

WORKDIR /app

RUN groupadd -r appuser && useradd -r -g appuser appuser

COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

COPY mcp_gateway/ ./mcp_gateway/

RUN chown -R appuser:appuser /app
USER appuser

EXPOSE 8080

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import httpx; httpx.get('http://localhost:8080/ready', timeout=2).raise_for_status()" || exit 1

CMD ["uvicorn", "mcp_gateway.main:app", "--host", "0.0.0.0", "--port", "8080"]
