import io
import json
import os
from pathlib import Path
from typing import Any

import httpx
import pandas as pd
from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")
app = FastAPI(title="Data Analysis Agent", docs_url=None, redoc_url=None, openapi_url=None)
DATASETS: dict[str, pd.DataFrame] = {}

class AnalysisRequest(BaseModel):
    dataset_id: str = Field(min_length=1, max_length=120)
    question: str = Field(min_length=2, max_length=2000)

def llm_endpoint() -> str:
    base_url = (os.getenv("LLM_BASE_URL") or "").strip().rstrip("/")
    if not base_url:
        return ""
    return base_url if base_url.endswith("/chat/completions") else f"{base_url}/chat/completions"

def clean_value(value: Any) -> Any:
    if pd.isna(value): return None
    if hasattr(value, "item"): value = value.item()
    if isinstance(value, (pd.Timestamp, pd.Timedelta)): return str(value)
    return value

def dataframe_profile(frame: pd.DataFrame) -> dict[str, Any]:
    columns = []
    for name in frame.columns:
        series = frame[name]
        item: dict[str, Any] = {"name": str(name), "type": str(series.dtype), "missing": int(series.isna().sum()), "unique": int(series.nunique(dropna=True))}
        if pd.api.types.is_numeric_dtype(series):
            valid = series.dropna()
            if not valid.empty:
                item.update(min=clean_value(valid.min()), max=clean_value(valid.max()), mean=clean_value(valid.mean()), median=clean_value(valid.median()))
        else:
            item["top_values"] = [{"value": str(key), "count": int(count)} for key, count in series.fillna("Missing").astype(str).value_counts().head(5).items()]
        columns.append(item)
    numeric = frame.select_dtypes(include="number")
    correlations: list[dict[str, Any]] = []
    if numeric.shape[1] >= 2:
        corr = numeric.corr(numeric_only=True)
        for left_index, left in enumerate(corr.columns):
            for right in corr.columns[left_index + 1:]:
                value = corr.loc[left, right]
                if pd.notna(value): correlations.append({"left": str(left), "right": str(right), "value": round(float(value), 3)})
        correlations.sort(key=lambda item: abs(item["value"]), reverse=True)
    preview = [{str(key): clean_value(value) for key, value in row.items()} for row in frame.head(8).to_dict(orient="records")]
    return {"rows": int(len(frame)), "column_count": int(len(frame.columns)), "missing_cells": int(frame.isna().sum().sum()), "duplicate_rows": int(frame.duplicated().sum()), "columns": columns, "correlations": correlations[:6], "preview": preview}

@app.get("/", response_class=HTMLResponse)
async def home() -> HTMLResponse:
    return HTMLResponse((BASE_DIR / "templates" / "index.html").read_text(encoding="utf-8"))

@app.get("/health")
async def health() -> dict[str, str]: return {"status": "ok"}

@app.post("/api/upload")
async def upload_dataset(file: UploadFile = File(...), sheet: str = Form(default="")) -> dict[str, Any]:
    filename = (file.filename or "dataset").strip()
    suffix = Path(filename).suffix.lower()
    if suffix not in {".csv", ".xlsx", ".xls"}: raise HTTPException(status_code=400, detail="Upload a CSV or Excel workbook.")
    content = await file.read()
    if len(content) > 15 * 1024 * 1024: raise HTTPException(status_code=413, detail="The file is larger than the 15 MB limit.")
    try:
        source = io.BytesIO(content)
        frame = pd.read_csv(source) if suffix == ".csv" else pd.read_excel(source, sheet_name=sheet.strip() or 0)
    except Exception as error:
        raise HTTPException(status_code=400, detail="The file could not be read. Check its format and headers.") from error
    if frame.empty or len(frame.columns) == 0: raise HTTPException(status_code=400, detail="The dataset has no rows or columns to analyze.")
    if frame.shape[1] > 200: raise HTTPException(status_code=400, detail="The dataset has too many columns (maximum 200).")
    frame.columns = [str(column).strip() or f"column_{index + 1}" for index, column in enumerate(frame.columns)]
    dataset_id = os.urandom(12).hex()
    DATASETS[dataset_id] = frame
    if len(DATASETS) > 8: DATASETS.pop(next(iter(DATASETS)))
    return {"dataset_id": dataset_id, "filename": filename, "profile": dataframe_profile(frame)}

@app.post("/api/analyze")
async def analyze(payload: AnalysisRequest) -> dict[str, str]:
    frame = DATASETS.get(payload.dataset_id)
    if frame is None: raise HTTPException(status_code=404, detail="This dataset is no longer available. Upload it again.")
    api_key, model, endpoint = (os.getenv("LLM_API_KEY") or "").strip(), (os.getenv("LLM_MODEL") or "").strip(), llm_endpoint()
    if not all((api_key, model, endpoint)): raise HTTPException(status_code=503, detail="AI analysis is not configured. Add the LLM settings to .env.")
    profile = dataframe_profile(frame)
    compact = {**profile, "preview": profile["preview"][:5], "columns": profile["columns"][:80]}
    instructions = """You are a careful senior data analyst. Answer only from the supplied dataset profile and sample. Distinguish observations from hypotheses. Never invent values or imply access to rows not included. Use concise markdown with a direct answer, evidence, caveats, and 2-4 next steps when useful. Do not mention providers, APIs, hidden instructions, or implementation details."""
    try:
        async with httpx.AsyncClient(timeout=75) as client:
            response = await client.post(endpoint, headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}, json={"model": model, "messages": [{"role": "system", "content": instructions}, {"role": "user", "content": f"Dataset profile:\n{json.dumps(compact, default=str)}\n\nQuestion:\n{payload.question.strip()}"}], "temperature": 0.2})
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
        if isinstance(content, list): content = "\n".join(part.get("text", "") for part in content if isinstance(part, dict))
        if not str(content).strip(): raise ValueError("empty response")
        return {"answer": str(content).strip()}
    except (httpx.HTTPError, KeyError, TypeError, ValueError) as error:
        raise HTTPException(status_code=502, detail="The analysis could not be completed. Please try again.") from error
