"""Proxy /v1/chat/completions to the Hermes gateway API server."""
import os
import httpx
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse, JSONResponse

router = APIRouter(tags=["chat-proxy"])

GATEWAY_URL = os.environ.get("HERMES_GATEWAY_URL", "http://127.0.0.1:8642")


@router.post("/v1/chat/completions")
async def proxy_chat_completions(request: Request):
    body = await request.body()
    headers = {
        k: v for k, v in request.headers.items()
        if k.lower() not in ("host", "content-length", "transfer-encoding")
    }

    # Check if streaming
    try:
        import json
        payload = json.loads(body)
        is_stream = payload.get("stream", False)
    except Exception:
        is_stream = False

    async with httpx.AsyncClient(timeout=300) as client:
        if is_stream:
            req = client.build_request(
                "POST",
                f"{GATEWAY_URL}/v1/chat/completions",
                content=body,
                headers=headers,
            )
            resp = await client.send(req, stream=True)

            async def stream_gen():
                async for chunk in resp.aiter_bytes():
                    yield chunk

            return StreamingResponse(
                stream_gen(),
                status_code=resp.status_code,
                media_type=resp.headers.get("content-type", "text/event-stream"),
            )
        else:
            resp = await client.post(
                f"{GATEWAY_URL}/v1/chat/completions",
                content=body,
                headers=headers,
            )
            return JSONResponse(
                content=resp.json(),
                status_code=resp.status_code,
            )
