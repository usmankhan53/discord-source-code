import json
import os
import re
from io import BytesIO
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from docx import Document
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from openai import AsyncOpenAI
from pydantic import BaseModel, Field
from pypdf import PdfReader


ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT.parent / ".env")

app = FastAPI(title="Meeting Notes Generator", docs_url="/api/docs")
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")


class NotesRequest(BaseModel):
    transcript: str = Field(min_length=20, max_length=100_000)
    meeting_title: str = Field(default="Untitled meeting", max_length=160)
    tone: Literal["concise", "detailed", "executive"] = "concise"


class ActionItem(BaseModel):
    task: str
    owner: str = "Unassigned"
    due_date: str = "Not specified"


class NotesResponse(BaseModel):
    title: str
    overview: str
    key_points: list[str]
    decisions: list[str]
    action_items: list[ActionItem]
    follow_ups: list[str]


def get_client() -> tuple[AsyncOpenAI, str]:
    api_key = os.getenv("OPENAI_API_KEY") or os.getenv("LLM_API_KEY")
    if not api_key:
        raise HTTPException(
            status_code=503,
            detail="The LLM API key is not configured in the environment.",
        )
    kwargs = {"api_key": api_key}
    base_url = os.getenv("OPENAI_BASE_URL") or os.getenv("LLM_BASE_URL")
    if base_url:
        kwargs["base_url"] = base_url
    model = os.getenv("LLM_MODEL") or os.getenv("OPENAI_MODEL") or "gpt-4o-mini"
    return AsyncOpenAI(**kwargs), model


SYSTEM_PROMPT = """You are an expert meeting analyst. Convert the transcript into accurate,
useful notes. Never invent facts, owners, dates, or decisions. If an owner or due date is
not explicitly stated, use the documented fallback values. Keep each list item standalone.
Return only valid JSON matching this shape:
{
  "title": "string",
  "overview": "string",
  "key_points": ["string"],
  "decisions": ["string"],
  "action_items": [{"task":"string","owner":"string","due_date":"string"}],
  "follow_ups": ["string"]
}"""


@app.get("/", include_in_schema=False)
async def index():
    return FileResponse(ROOT / "static" / "index.html")


@app.get("/api/health")
async def health():
    return {"status": "ok", "llm_configured": bool(os.getenv("OPENAI_API_KEY") or os.getenv("LLM_API_KEY"))}


MAX_UPLOAD_BYTES = 10 * 1024 * 1024
SUPPORTED_EXTENSIONS = {".txt", ".vtt", ".srt", ".docx", ".pdf"}


def clean_caption_text(text: str, extension: str) -> str:
    text = text.replace("\ufeff", "").replace("\r\n", "\n")
    if extension in {".vtt", ".srt"}:
        kept = []
        timestamp = re.compile(r"^\s*\d{1,2}:\d{2}(?::\d{2})?[.,]\d{3}\s*-->")
        for line in text.splitlines():
            value = line.strip()
            if not value or value == "WEBVTT" or value.isdigit() or timestamp.match(value):
                continue
            value = re.sub(r"<[^>]+>", "", value)
            if not kept or value != kept[-1]:
                kept.append(value)
        text = "\n".join(kept)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


@app.post("/api/upload")
async def upload_transcript(file: UploadFile = File(...)):
    filename = Path(file.filename or "transcript").name
    extension = Path(filename).suffix.lower()
    if extension not in SUPPORTED_EXTENSIONS:
        raise HTTPException(status_code=415, detail="Upload a TXT, VTT, SRT, DOCX, or PDF transcript.")
    content = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="The transcript exceeds the 10 MB limit.")
    if not content:
        raise HTTPException(status_code=400, detail="The selected file is empty.")
    try:
        if extension == ".docx":
            document = Document(BytesIO(content))
            text = "\n".join(p.text for p in document.paragraphs if p.text.strip())
        elif extension == ".pdf":
            text = "\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(content)).pages)
        else:
            try:
                text = content.decode("utf-8")
            except UnicodeDecodeError:
                text = content.decode("utf-16")
        text = clean_caption_text(text, extension)
    except Exception as exc:
        raise HTTPException(status_code=422, detail="We couldn't read this transcript. Try exporting it as TXT or VTT.") from exc
    if len(text) < 20:
        raise HTTPException(status_code=422, detail="No readable transcript text was found.")
    if len(text) > 100_000:
        raise HTTPException(status_code=413, detail="The transcript is over 100,000 characters. Please shorten it.")
    title = Path(filename).stem.replace("_", " ").replace("-", " ").strip().title()
    return {"filename": filename, "title": title, "transcript": text, "characters": len(text)}

@app.post("/api/generate", response_model=NotesResponse)
async def generate_notes(payload: NotesRequest):
    client, model = get_client()
    prompt = f"Meeting title: {payload.meeting_title}\nStyle: {payload.tone}\n\nTranscript:\n{payload.transcript}"
    try:
        response = await client.chat.completions.create(
            model=model,
            temperature=0.2,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
        )
        raw = response.choices[0].message.content or "{}"
        return NotesResponse.model_validate(json.loads(raw))
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Notes could not be generated. Check the LLM configuration and try again.") from exc
