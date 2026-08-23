from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from openai import AsyncOpenAI
from pydantic import BaseModel, Field

PROJECT_ROOT = Path(__file__).resolve().parent
load_dotenv(PROJECT_ROOT / ".env")

app = FastAPI(title="Forge", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=PROJECT_ROOT / "static"), name="static")


class AgentRequest(BaseModel):
    message: str = Field(min_length=1, max_length=12_000)
    context: str = Field(default="", max_length=20_000)
    mode: Literal["build", "explain", "debug"] = "build"


def llm_client() -> tuple[AsyncOpenAI, str]:
    api_key = os.getenv("LLM_API_KEY") or os.getenv("ROUTEAPI_KEY")
    base_url = os.getenv("LLM_BASE_URL") or os.getenv("ROUTEAPI_BASE_URL")
    model = os.getenv("LLM_MODEL") or os.getenv("ROUTEAPI_MODEL")
    if not api_key or not base_url or not model:
        raise HTTPException(status_code=503, detail="The language model is not configured. Add LLM_API_KEY, LLM_BASE_URL, and LLM_MODEL to .env.")
    return AsyncOpenAI(api_key=api_key, base_url=base_url), model


@app.get("/", response_class=HTMLResponse)
async def home() -> HTMLResponse:
    return HTMLResponse((PROJECT_ROOT / "templates" / "index.html").read_text(encoding="utf-8"))


@app.get("/api/files")
async def list_files() -> dict[str, list[str]]:
    ignored = {".git", ".venv", "__pycache__", "node_modules"}
    files = [
        str(path.relative_to(PROJECT_ROOT)).replace("\\", "/")
        for path in PROJECT_ROOT.rglob("*")
        if path.is_file() and not any(part in ignored for part in path.relative_to(PROJECT_ROOT).parts)
    ]
    return {"files": sorted(files)[:200]}


@app.post("/api/agent")
async def run_agent(request: AgentRequest) -> dict[str, str]:
    client, model = llm_client()
    instructions = """You are Forge, a precise senior software engineer working inside a project.
Give immediately useful coding help. Be concise, state assumptions, and return complete code only when it is requested.
Never claim to have changed files or run commands. When suggesting changes, name the target files.
Format code with fenced Markdown blocks and explain important tradeoffs briefly."""
    notes = {
        "build": "Focus on a practical implementation plan and the code needed to build it.",
        "explain": "Teach the concept clearly, using the project context when relevant.",
        "debug": "Diagnose likely causes and propose a testable fix.",
    }
    content = f"Mode: {request.mode}\n{notes[request.mode]}\n\nRequest:\n{request.message}"
    if request.context.strip():
        content += f"\n\nProject context:\n{request.context.strip()}"
    try:
        response = await client.chat.completions.create(
            model=model,
            temperature=0.25,
            messages=[{"role": "system", "content": instructions}, {"role": "user", "content": content}],
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail="The language model could not complete the request.") from exc
    return {"answer": response.choices[0].message.content or "I couldn't generate a response for that request."}
