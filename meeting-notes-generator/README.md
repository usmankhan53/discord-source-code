# Meeting Notes Generator

A focused AI meeting-notes workspace built with FastAPI and Tailwind CSS.

## Run locally

```powershell
cd meeting-notes-generator
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Open <http://127.0.0.1:8000>. The backend reads `OPENAI_API_KEY`, optional
`OPENAI_BASE_URL`, and `LLM_MODEL` (or `OPENAI_MODEL`) from the environment.

