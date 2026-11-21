import hmac
from contextlib import asynccontextmanager
from typing import Annotated

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from mcp_gateway.config import settings

_HOP_BY_HOP_HEADERS = frozenset({
    "connection",
    "content-encoding",
    "content-length",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
})


def _safe_error_json(response: httpx.Response) -> dict:
    try:
        data = response.json()
        if isinstance(data, dict):
            return data
    except ValueError:
        pass
    return {"error": {"code": -32603, "message": f"Upstream HTTP {response.status_code}"}}


def _filtered_headers(headers: httpx.Headers) -> dict[str, str]:
    return {k: v for k, v in headers.items() if k.lower() not in _HOP_BY_HOP_HEADERS}


class JSONRPCRequest(BaseModel):
    jsonrpc: str = "2.0"
    method: str
    params: dict | None = None
    id: str | int | None = None


class JSONRPCResponse(BaseModel):
    jsonrpc: str = "2.0"
    result: dict | None = None
    error: dict | None = None
    id: str | int | None = None


http_client: httpx.AsyncClient | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global http_client
    http_client = httpx.AsyncClient(
        base_url=settings.api_base_url,
        timeout=httpx.Timeout(30.0, connect=10.0),
        headers={"Authorization": f"Bearer {settings.api_key}"},
    )
    yield
    await http_client.aclose()


app = FastAPI(
    title="MCP Gateway",
    version="1.0.0",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
    lifespan=lifespan,
)


def verify_gateway_key(
    x_gateway_key: Annotated[str | None, Header()] = None,
) -> None:
    expected = (settings.gateway_key or "").strip()
    if not expected:
        raise HTTPException(status_code=503, detail="Gateway authentication not configured")
    if not hmac.compare_digest(x_gateway_key or "", expected):
        raise HTTPException(status_code=401, detail="Invalid gateway key")


@app.get("/health")
def health():
    return {"status": "ok", "service": "mcp-gateway"}


@app.get("/ready")
async def ready():
    try:
        if http_client is None:
            raise RuntimeError("Cliente HTTP não inicializado")
        response = await http_client.get("/ready")
        response.raise_for_status()
    except (httpx.HTTPError, RuntimeError) as exc:
        raise HTTPException(status_code=502, detail="API indisponível") from exc
    return {"status": "ready"}


@app.post("/mcp", dependencies=[Depends(verify_gateway_key)])
async def mcp_proxy(request: Request):
    body = await request.json()

    if not isinstance(body, dict):
        return JSONResponse(
            status_code=400,
            content=JSONRPCResponse(
                id=body.get("id") if isinstance(body, dict) else None,
                error={"code": -32700, "message": "Parse error"},
            ).model_dump(),
        )

    rpc_request = JSONRPCRequest(**body)

    try:
        if http_client is None:
            raise RuntimeError("HTTP client not initialized")
        resp = await http_client.post("/mcp", json=rpc_request.model_dump(exclude_none=True))
        resp.raise_for_status()
        return Response(
            content=resp.content,
            media_type="application/json",
            headers=_filtered_headers(resp.headers),
        )
    except httpx.HTTPStatusError as e:
        return JSONResponse(
            status_code=e.response.status_code,
            content=_safe_error_json(e.response),
        )
    except httpx.RequestError as e:
        return JSONResponse(
            status_code=502,
            content=JSONRPCResponse(
                id=rpc_request.id,
                error={"code": -32603, "message": f"Upstream error: {e!s}"},
            ).model_dump(),
        )


@app.post("/mcp/batch", dependencies=[Depends(verify_gateway_key)])
async def mcp_batch_proxy(request: Request):
    body = await request.json()

    if not isinstance(body, list):
        return JSONResponse(
            status_code=400,
            content={"error": "Batch request must be a JSON array"},
        )

    results = []
    for item in body:
        if not isinstance(item, dict):
            results.append(
                JSONRPCResponse(
                    id=item.get("id") if isinstance(item, dict) else None,
                    error={"code": -32700, "message": "Parse error"},
                ).model_dump()
            )
            continue

        rpc_request = JSONRPCRequest(**item)
        try:
            if http_client is None:
                raise RuntimeError("HTTP client not initialized")
            resp = await http_client.post("/mcp", json=rpc_request.model_dump(exclude_none=True))
            resp.raise_for_status()
            results.append(resp.json())
        except httpx.HTTPStatusError as e:
            results.append(_safe_error_json(e.response))
        except httpx.RequestError as e:
            results.append(
                JSONRPCResponse(
                    id=rpc_request.id,
                    error={"code": -32603, "message": f"Upstream error: {e!s}"},
                ).model_dump()
            )

    return JSONResponse(content=results)
