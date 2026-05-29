from fastapi import FastAPI, Header, HTTPException, Request
from pydantic import BaseModel
from typing import List, Optional, Any, Dict
import httpx
import os
import uuid

app = FastAPI()

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://ollama.local-ai.svc.cluster.local:11434")
PROXY_KEY = os.getenv("PROXY_KEY", "secret")


class Message(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    model: str
    messages: List[Message]
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None


def extract_text_from_ollama(resp_json: Any, raw_text: str) -> str:
    # Try common shapes
    if isinstance(resp_json, dict):
        # Ollama may return {'choices':[{'message':{'content': '...'}}]}
        choices = resp_json.get("choices")
        if choices and isinstance(choices, list) and len(choices) > 0:
            first = choices[0]
            if isinstance(first, dict):
                msg = first.get("message") or first.get("text")
                if isinstance(msg, dict):
                    return msg.get("content") or msg.get("text") or raw_text
                if isinstance(msg, str):
                    return msg
        # fallback to message
        message = resp_json.get("message")
        if isinstance(message, dict):
            return message.get("content") or message.get("text") or raw_text
        if "text" in resp_json and isinstance(resp_json["text"], str):
            return resp_json["text"]
    return raw_text


@app.post("/v1/chat/completions")
async def chat_completions(request: ChatRequest, authorization: Optional[str] = Header(None)):
    # simple API key check (Bearer)
    if PROXY_KEY:
        if not authorization or not authorization.lower().startswith("bearer "):
            raise HTTPException(status_code=401, detail="missing Authorization Bearer token")
        token = authorization.split()[1]
        if token != PROXY_KEY:
            raise HTTPException(status_code=403, detail="invalid api key")

    payload = {"model": request.model, "messages": [m.dict() for m in request.messages]}

    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            r = await client.post(f"{OLLAMA_URL}/api/chat", json=payload)
            r.raise_for_status()
            data = r.json()
        except httpx.HTTPStatusError as e:
            raise HTTPException(status_code=502, detail=f"ollama error: {e.response.text}")
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"ollama request failed: {str(e)}")

    text = extract_text_from_ollama(data, r.text if r is not None else "")

    response = {
        "id": f"ruv-adapter-{uuid.uuid4().hex}",
        "object": "chat.completion",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": text},
                "finish_reason": "stop",
            }
        ],
    }
    return response


@app.get("/healthz")
def healthz():
    return {"ok": True}
