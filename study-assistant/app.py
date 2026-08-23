from __future__ import annotations

import json
import os
import re
import sqlite3
import uuid
from typing import Any
from pathlib import Path

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

load_dotenv(Path(__file__).with_name(".env"))


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=12000)
    system_prompt: str | None = Field(default=None, max_length=4000)


class StudyRequest(BaseModel):
    topic: str = Field(min_length=1, max_length=240)
    task: str = Field(min_length=1, max_length=12000)
    mode: str = Field(default="coach", pattern="^(coach|plan|quiz|flashcards)$")


class QuizRequest(BaseModel):
    topic: str = Field(min_length=1, max_length=240)
    task: str = Field(min_length=1, max_length=4000)
    count: int = Field(default=5, ge=3, le=10)


class QuizSubmission(BaseModel):
    answers: dict[str, int]


class PlanRequest(BaseModel):
    topic: str = Field(min_length=1, max_length=240)
    task: str = Field(min_length=1, max_length=4000)


class CardsRequest(BaseModel):
    topic: str = Field(min_length=1, max_length=240)
    task: str = Field(min_length=1, max_length=4000)
    count: int = Field(default=8, ge=3, le=20)


STUDY_INSTRUCTIONS = """You are a warm, rigorous AI study assistant. Help the learner
understand rather than merely give answers. Be concise and use clear headings,
examples, and active-recall questions when useful. For quizzes, wait to reveal
answers until after the learner responds unless explicitly asked. For flashcards,
use 'Front:' and 'Back:' pairs. Never claim a task was completed by the learner."""

DB_PATH = Path(__file__).with_name("study_assistant.db")


def database() -> sqlite3.Connection:
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("CREATE TABLE IF NOT EXISTS quizzes (id TEXT PRIMARY KEY, payload TEXT NOT NULL)")
    return connection


def json_from_model(content: str) -> Any:
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", content.strip(), flags=re.IGNORECASE)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise RuntimeError("The study material could not be formatted. Please try again.") from exc


def _environment(primary: str, legacy: str) -> str:
    return os.getenv(primary, os.getenv(legacy, "")).strip()


def settings() -> tuple[str, str, str]:
    """Return settings for the existing OpenAI-compatible LLM environment."""
    api_key = _environment("LLM_API_KEY", "ROUTEAPI_KEY")
    model = _environment("LLM_MODEL", "ROUTEAPI_MODEL")
    base_url = _environment("LLM_BASE_URL", "ROUTEAPI_BASE_URL").rstrip("/")
    if not all((api_key, model, base_url)):
        raise RuntimeError("The LLM environment configuration is incomplete.")
    return api_key, model, base_url


async def complete(message: str, system_prompt: str | None = None) -> str:
    """Call the configured OpenAI-compatible chat-completions endpoint."""
    api_key, model, base_url = settings()
    messages = ([{"role": "system", "content": system_prompt}] if system_prompt else [])
    messages.append({"role": "user", "content": message})
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                f"{base_url}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={"model": model, "messages": messages, "temperature": 0.7},
            )
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
        if not isinstance(content, str) or not content.strip():
            raise ValueError("The model returned an empty response.")
        return content.strip()
    except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as exc:
        raise RuntimeError("Unable to get a response from the configured model.") from exc


async def generate_json(instruction: str) -> Any:
    response = await complete(instruction, STUDY_INSTRUCTIONS + " Return valid JSON only; no markdown or commentary.")
    return json_from_model(response)


app = FastAPI(title="Workspace", docs_url=None, redoc_url=None)
@app.get("/", include_in_schema=False)
async def home() -> FileResponse:
    return FileResponse(Path(__file__).parent / "templates" / "index.html")


@app.get("/status", include_in_schema=False)
async def status() -> dict[str, bool]:
    try:
        settings()
        return {"ready": True}
    except RuntimeError:
        return {"ready": False}


@app.post("/chat", include_in_schema=False)
async def chat(request: ChatRequest) -> dict[str, str]:
    try:
        return {"answer": await complete(request.message, request.system_prompt)}
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/study", include_in_schema=False)
async def study(request: StudyRequest) -> dict[str, str]:
    prompts = {
        "coach": "Teach this topic and guide the learner through the request.",
        "plan": "Create a practical, time-boxed study plan with review checkpoints.",
        "quiz": "Create a short formative quiz. Do not include the answers yet.",
        "flashcards": "Create high-quality active-recall flashcards.",
    }
    message = f"Topic: {request.topic}\nMode: {request.mode}\n\n{prompts[request.mode]}\n\nLearner request: {request.task}"
    try:
        return {"answer": await complete(message, STUDY_INSTRUCTIONS)}
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/plans", include_in_schema=False)
async def create_plan(request: PlanRequest) -> dict[str, Any]:
    prompt = f'''Create a study plan for {request.topic}. Learner goal: {request.task}
Return JSON exactly as {{"title":"...","summary":"...","tasks":[{{"title":"...","duration":"...","detail":"..."}}]}}. Include 3-8 ordered, concrete tasks.'''
    try:
        result = await generate_json(prompt)
        if not isinstance(result, dict) or not isinstance(result.get("tasks"), list):
            raise RuntimeError("The plan response was incomplete.")
        return result
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/flashcards", include_in_schema=False)
async def create_flashcards(request: CardsRequest) -> dict[str, Any]:
    prompt = f'''Create {request.count} concise active-recall flashcards about {request.topic}. Learner request: {request.task}
Return JSON exactly as {{"cards":[{{"front":"question","back":"answer"}}]}}. Each answer must stand alone.'''
    try:
        result = await generate_json(prompt)
        cards = result.get("cards") if isinstance(result, dict) else None
        if not isinstance(cards, list) or not cards:
            raise RuntimeError("The flashcard response was incomplete.")
        return {"cards": cards[:request.count]}
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/quizzes", include_in_schema=False)
async def create_quiz(request: QuizRequest) -> dict[str, Any]:
    prompt = f'''Create a {request.count}-question multiple-choice quiz about {request.topic}. Learner request: {request.task}
Return JSON exactly as {{"title":"...","questions":[{{"question":"...","options":["...","...","...","..."],"answer":0,"explanation":"..."}}]}}. answer is the zero-based correct option index. Make plausible distractors.'''
    try:
        quiz = await generate_json(prompt)
        questions = quiz.get("questions") if isinstance(quiz, dict) else None
        if not isinstance(questions, list) or len(questions) != request.count:
            raise RuntimeError("The quiz response was incomplete.")
        for question in questions:
            if not isinstance(question.get("options"), list) or len(question["options"]) != 4 or question.get("answer") not in range(4):
                raise RuntimeError("The quiz response was invalid.")
        quiz_id = str(uuid.uuid4())
        with database() as connection:
            connection.execute("INSERT INTO quizzes (id, payload) VALUES (?, ?)", (quiz_id, json.dumps(quiz)))
        public_questions = [{"question": item["question"], "options": item["options"]} for item in questions]
        return {"quiz_id": quiz_id, "title": quiz.get("title", f"{request.topic} quiz"), "questions": public_questions}
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/quizzes/{quiz_id}/submit", include_in_schema=False)
async def submit_quiz(quiz_id: str, submission: QuizSubmission) -> dict[str, Any]:
    with database() as connection:
        row = connection.execute("SELECT payload FROM quizzes WHERE id = ?", (quiz_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Quiz not found. Create a new quiz and try again.")
    quiz = json.loads(row["payload"])
    feedback, correct = [], 0
    for index, question in enumerate(quiz["questions"]):
        selected = submission.answers.get(str(index))
        is_correct = selected == question["answer"]
        correct += int(is_correct)
        feedback.append({"correct": is_correct, "correct_option": question["answer"], "explanation": question["explanation"]})
    return {"score": correct, "total": len(quiz["questions"]), "feedback": feedback}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
