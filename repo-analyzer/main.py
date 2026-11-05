import asyncio
import io
import os
import re
import zipfile
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx
from dotenv import dotenv_values, load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

APP_DIR = Path(__file__).resolve().parent
STATIC_DIR = APP_DIR / "static"
GITHUB_API = "https://api.github.com"
MAX_FILES = 180
MAX_SOURCE_FILES = 10
MAX_FILE_CHARS = 7_000
MAX_ARCHIVE_BYTES = 35 * 1024 * 1024

load_dotenv(APP_DIR / ".env")
DOTENV = {key: value for key, value in dotenv_values(APP_DIR / ".env").items() if value}


def setting(generic_name: str, suffix: str) -> str:
    """Use generic config first, then discover compatible local env keys."""
    direct = os.getenv(generic_name) or DOTENV.get(generic_name)
    if direct:
        return direct.strip()
    for key, value in DOTENV.items():
        if key.upper().endswith(suffix) and value:
            return value.strip()
    return ""


LLM_API_KEY = setting("LLM_API_KEY", "API_KEY")
LLM_MODEL = setting("LLM_MODEL", "MODEL")
LLM_BASE_URL = setting("LLM_BASE_URL", "BASE_URL")
GITHUB_TOKEN = setting("GITHUB_TOKEN", "GITHUB_TOKEN")

app = FastAPI(title="Repository Analyzer", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


class AnalyzeRequest(BaseModel):
    repository_url: str = Field(..., min_length=12, max_length=300)


def parse_repository_url(url: str) -> tuple[str, str]:
    value = url.strip().removesuffix("/").removesuffix(".git")
    match = re.search(r"github\.com[/:]([\w.-]+)/([\w.-]+)$", value, re.IGNORECASE)
    if not match:
        raise HTTPException(400, "Enter a valid public GitHub repository URL.")
    return match.group(1), match.group(2)


def github_headers() -> dict[str, str]:
    headers = {"Accept": "application/vnd.github+json"}
    if GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"
    return headers


async def github_json(client: httpx.AsyncClient, path: str) -> Any:
    response = await client.get(f"{GITHUB_API}{path}", headers=github_headers())
    if response.status_code == 404:
        raise HTTPException(404, "Repository not found or it is private.")
    if response.status_code in (403, 429):
        raise HTTPException(429, "GitHub is rate-limiting requests.")
    response.raise_for_status()
    return response.json()


def selected_files(blobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    preferred_names = {
        "readme.md", "package.json", "pyproject.toml", "requirements.txt",
        "dockerfile", "compose.yml", "docker-compose.yml",
    }
    preferred = [item for item in blobs if item["path"].lower() in preferred_names]
    source = [
        item for item in blobs
        if re.search(r"\.(py|ts|tsx|js|jsx|go|rs|java|rb|php|cs)$", item["path"], re.IGNORECASE)
    ]
    chosen: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in preferred + source[:MAX_SOURCE_FILES]:
        if item["path"] not in seen:
            chosen.append(item)
            seen.add(item["path"])
    return chosen


async def get_repository_context_from_api(owner: str, repo: str) -> tuple[dict[str, Any], str]:
    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
        metadata = await github_json(client, f"/repos/{owner}/{repo}")
        default_branch = metadata.get("default_branch", "main")
        tree = await github_json(client, f"/repos/{owner}/{repo}/git/trees/{quote(default_branch, safe='')}?recursive=1")
        blobs = [item for item in tree.get("tree", []) if item.get("type") == "blob"]
        paths = [item["path"] for item in blobs][:MAX_FILES]

        async def fetch_file(item: dict[str, Any]) -> str:
            try:
                raw_url = f"https://raw.githubusercontent.com/{owner}/{repo}/{quote(default_branch, safe='/')}/{quote(item['path'], safe='/')}"
                response = await client.get(raw_url)
                response.raise_for_status()
                return f"\n--- {item['path']} ---\n{response.text[:MAX_FILE_CHARS]}"
            except httpx.HTTPError:
                return ""

        excerpts = await asyncio.gather(*(fetch_file(item) for item in selected_files(blobs)))

    summary = {
        "name": metadata.get("full_name", f"{owner}/{repo}"),
        "description": metadata.get("description") or "No description provided.",
        "language": metadata.get("language") or "Not detected",
        "stars": metadata.get("stargazers_count", 0),
        "forks": metadata.get("forks_count", 0),
        "open_issues": metadata.get("open_issues_count", 0),
        "default_branch": default_branch,
        "file_count": len(blobs),
        "files": paths,
    }
    context = "Repository metadata:\n" + str(summary) + "\n\nSelected file contents:\n" + "".join(excerpts)
    return summary, context


async def get_repository_context_from_archive(owner: str, repo: str) -> tuple[dict[str, Any], str]:
    """Retrieve enough public repository context without GitHub's REST API."""
    repository_page = f"https://github.com/{owner}/{repo}"
    async with httpx.AsyncClient(timeout=httpx.Timeout(45.0, connect=15.0), follow_redirects=True) as client:
        page = await client.get(repository_page)
        if page.status_code == 404:
            raise HTTPException(404, "Repository not found or it is private.")
        if page.status_code >= 400:
            raise HTTPException(502, "Could not reach GitHub. Please try again shortly.")

        branch_match = re.search(
            r'"zipballUrl":"/[^\"]+/archive/refs/heads/([^\"]+)\.zip"',
            page.text,
        )
        default_branch = branch_match.group(1) if branch_match else "main"
        archive_url = f"https://codeload.github.com/{owner}/{repo}/zip/refs/heads/{quote(default_branch, safe='/')}"
        archive_response = await client.get(archive_url)
        if archive_response.status_code == 404:
            raise HTTPException(404, "Repository not found or its default branch is unavailable.")
        if archive_response.status_code >= 400:
            raise HTTPException(502, "Could not download the repository source. Please try again shortly.")
        if len(archive_response.content) > MAX_ARCHIVE_BYTES:
            raise HTTPException(413, "This repository is too large to analyze right now.")

    try:
        archive = zipfile.ZipFile(io.BytesIO(archive_response.content))
    except zipfile.BadZipFile as exc:
        raise HTTPException(502, "GitHub returned an invalid source archive.") from exc

    try:
        entries = [info for info in archive.infolist() if not info.is_dir()]
        if not entries:
            raise HTTPException(422, "The repository does not contain any files to analyze.")
        root = entries[0].filename.split("/", 1)[0] + "/"
        blobs = [
            {"path": info.filename.removeprefix(root), "member": info.filename, "size": info.file_size}
            for info in entries
            if info.filename.startswith(root) and info.filename.removeprefix(root)
        ]
        excerpts: list[str] = []
        for item in selected_files(blobs):
            if item.get("size", 0) > MAX_ARCHIVE_BYTES:
                continue
            try:
                content = archive.read(item["member"])[:MAX_FILE_CHARS].decode("utf-8", errors="replace")
                excerpts.append(f"\n--- {item['path']} ---\n{content}")
            except (KeyError, OSError, RuntimeError, zipfile.BadZipFile):
                continue
    finally:
        archive.close()

    summary = {
        "name": f"{owner}/{repo}",
        "description": "Public GitHub repository (source archive fallback).",
        "language": "Not detected",
        "stars": 0,
        "forks": 0,
        "open_issues": 0,
        "default_branch": default_branch,
        "file_count": len(blobs),
        "files": [item["path"] for item in blobs][:MAX_FILES],
    }
    context = "Repository metadata:\n" + str(summary) + "\n\nSelected file contents:\n" + "".join(excerpts)
    return summary, context


async def get_repository_context(owner: str, repo: str) -> tuple[dict[str, Any], str]:
    try:
        return await get_repository_context_from_api(owner, repo)
    except HTTPException as exc:
        if exc.status_code != 429:
            raise
        return await get_repository_context_from_archive(owner, repo)


async def request_analysis(context: str) -> str:
    if not (LLM_API_KEY and LLM_MODEL and LLM_BASE_URL):
        raise HTTPException(500, "Missing LLM configuration. Add LLM_API_KEY, LLM_MODEL, and LLM_BASE_URL to .env, then restart the server.")
    prompt = (
        "You are a senior software engineer reviewing a GitHub repository. Analyze only the "
        "supplied repository context. Return clean Markdown with these concise sections: "
        "Overview, Architecture, Technology, Key Files, Code Health, Risks & Gaps, and "
        "Recommended Next Steps. Be specific, distinguish facts from inferences, and never "
        "claim you ran the project or accessed files not provided."
    )
    payload = {
        "model": LLM_MODEL,
        "messages": [
            {"role": "system", "content": prompt},
            {"role": "user", "content": context},
        ],
        "temperature": 0.25,
    }
    endpoint = LLM_BASE_URL.rstrip("/")
    if not endpoint.endswith("/chat/completions"):
        endpoint += "/chat/completions"
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=15.0)) as client:
            response = await client.post(
                endpoint,
                headers={"Authorization": f"Bearer {LLM_API_KEY}", "Content-Type": "application/json"},
                json=payload,
            )
        if response.status_code in (401, 403):
            raise HTTPException(502, "The configured AI service rejected the API key.")
        if response.status_code == 429:
            raise HTTPException(429, "The AI service is busy. Please try again in a moment.")
        response.raise_for_status()
        content = response.json().get("choices", [{}])[0].get("message", {}).get("content")
        if isinstance(content, list):
            content = "".join(str(part.get("text", "")) for part in content if isinstance(part, dict))
        if not content:
            raise ValueError("The AI service returned no analysis.")
        return str(content).strip()
    except HTTPException:
        raise
    except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError) as exc:
        raise HTTPException(502, "Could not generate the AI analysis. Please try again.") from exc


@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.post("/api/analyze")
async def analyze(request: AnalyzeRequest) -> dict[str, Any]:
    owner, repo = parse_repository_url(request.repository_url)
    metadata, context = await get_repository_context(owner, repo)
    analysis = await request_analysis(context)
    return {"repository": metadata, "analysis": analysis}


@app.get("/api/health")
async def health() -> dict[str, bool]:
    return {"ok": True, "configured": bool(LLM_API_KEY and LLM_MODEL and LLM_BASE_URL)}