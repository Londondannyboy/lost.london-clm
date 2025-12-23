"""
VIC CLM Server - Custom Language Model for Hume EVI

This FastAPI server implements the OpenAI-compatible /chat/completions endpoint
that Hume EVI requires for Custom Language Model integration.

All responses are validated through Pydantic AI to ensure factual accuracy
before being spoken by the voice assistant.
"""

import os
import time
import json
from uuid import uuid4
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Security, HTTPException
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
from openai.types.chat import ChatCompletionChunk
from openai.types.chat.chat_completion_chunk import Choice, ChoiceDelta
import tiktoken

from .agent import generate_response
from .database import Database
from .tools import save_user_message

# Token for authenticating Hume requests
CLM_AUTH_TOKEN = os.environ.get("CLM_AUTH_TOKEN", "")

# Tokenizer for streaming response chunks
enc = tiktoken.encoding_for_model("gpt-4o")

# Security
security = HTTPBearer(auto_error=False)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage database connection lifecycle."""
    # Startup
    yield
    # Shutdown - close database pool
    await Database.close()


app = FastAPI(
    title="VIC CLM",
    description="Custom Language Model for Lost London voice assistant",
    version="2.0.0",
    lifespan=lifespan,
)

# CORS for development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def verify_token(credentials: HTTPAuthorizationCredentials | None) -> bool:
    """Verify the Bearer token from Hume."""
    if not CLM_AUTH_TOKEN:
        # No token configured - allow all requests (dev mode)
        return True
    if not credentials:
        return False
    return credentials.credentials == CLM_AUTH_TOKEN


def extract_user_message(messages: list[dict]) -> str | None:
    """Extract the last user message from conversation history."""
    for msg in reversed(messages):
        if msg.get("role") == "user":
            content = msg.get("content", "")
            # Handle both string and list content formats
            if isinstance(content, list):
                # Extract text from content blocks
                text_parts = [
                    part.get("text", "")
                    for part in content
                    if part.get("type") == "text"
                ]
                return " ".join(text_parts)
            return content
    return None


def extract_session_id(request: Request) -> str | None:
    """Extract custom_session_id from query params."""
    return request.query_params.get("custom_session_id")


async def stream_response(text: str, session_id: str | None = None):
    """
    Stream response as OpenAI-compatible ChatCompletionChunks.

    Hume EVI expects responses in the exact format of OpenAI's
    streaming chat completions API.
    """
    chunk_id = str(uuid4())
    created = int(time.time())

    # Stream token by token for natural speech pacing
    tokens = enc.encode(text)

    for i, token_id in enumerate(tokens):
        token_text = enc.decode([token_id])

        chunk = ChatCompletionChunk(
            id=chunk_id,
            choices=[
                Choice(
                    delta=ChoiceDelta(
                        content=token_text,
                        role="assistant" if i == 0 else None,
                    ),
                    finish_reason=None,
                    index=0,
                )
            ],
            created=created,
            model="vic-clm-2.0",
            object="chat.completion.chunk",
            system_fingerprint=session_id,  # Preserve session ID
        )

        yield f"data: {chunk.model_dump_json(exclude_none=True)}\n\n"

    # Send final chunk with finish_reason
    final_chunk = ChatCompletionChunk(
        id=chunk_id,
        choices=[
            Choice(
                delta=ChoiceDelta(),
                finish_reason="stop",
                index=0,
            )
        ],
        created=created,
        model="vic-clm-2.0",
        object="chat.completion.chunk",
        system_fingerprint=session_id,
    )
    yield f"data: {final_chunk.model_dump_json(exclude_none=True)}\n\n"

    # Signal end of stream
    yield "data: [DONE]\n\n"


@app.post("/chat/completions")
async def chat_completions(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Security(security),
):
    """
    OpenAI-compatible chat completions endpoint for Hume CLM.

    Receives conversation history, generates a validated response using
    Pydantic AI, and streams it back in OpenAI's format.
    """
    # Verify authentication
    if not verify_token(credentials):
        raise HTTPException(status_code=401, detail="Invalid or missing auth token")

    try:
        body = await request.json()
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    messages = body.get("messages", [])
    session_id = extract_session_id(request)

    # Extract the user's message
    user_message = extract_user_message(messages)

    if not user_message:
        # No user message - return a prompt
        fallback = "I didn't quite catch that. Could you say that again?"
        return StreamingResponse(
            stream_response(fallback, session_id),
            media_type="text/event-stream",
        )

    # Save user message to Zep for memory (fire and forget)
    if session_id:
        # Don't await - let it run in background
        import asyncio
        asyncio.create_task(save_user_message(session_id, user_message, "user"))

    # Generate validated response using Pydantic AI agent
    response_text = await generate_response(user_message, session_id)

    # Save assistant response to Zep
    if session_id:
        import asyncio
        asyncio.create_task(save_user_message(session_id, response_text, "assistant"))

    # Stream the response
    return StreamingResponse(
        stream_response(response_text, session_id),
        media_type="text/event-stream",
    )


@app.get("/")
async def root():
    """Health check and info endpoint."""
    return {
        "status": "ok",
        "service": "VIC CLM",
        "version": "2.0.0",
        "description": "Custom Language Model for Lost London voice assistant",
        "endpoint": "/chat/completions",
    }


@app.get("/health")
async def health():
    """Health check for monitoring."""
    return {"status": "healthy"}


# For local development with uvicorn
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
