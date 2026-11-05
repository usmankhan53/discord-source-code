# Repository Analyzer

A FastAPI web app that generates an AI-assisted review of public GitHub repositories.

## Run locally

1. Create and activate a virtual environment.
2. Install dependencies: `pip install -r requirements.txt`
3. Copy `.env.example` to `.env` and set `LLM_API_KEY`, `LLM_MODEL`, `LLM_BASE_URL`, and optionally `GITHUB_TOKEN`.
4. Start the app: `uvicorn main:app --reload`
5. Visit `http://127.0.0.1:8000`

The application uses the same environment convention as `browser-ai-agent`: `LLM_API_KEY`, `LLM_MODEL`, `LLM_BASE_URL`, and optionally `GITHUB_TOKEN`. The base URL may either include `/chat/completions` or stop at the API version; the application handles both. The UI and user-facing text do not expose the underlying provider.
