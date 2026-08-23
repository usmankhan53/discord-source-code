# Forge Coding Agent

A focused coding assistant built with FastAPI and Tailwind CSS.

## Run locally

1. Install dependencies: `pip install -r requirements.txt`
2. Set `LLM_API_KEY`, `LLM_MODEL`, and `LLM_BASE_URL` in `.env`.
3. Start the app: `uvicorn app:app --reload`
4. Open `http://127.0.0.1:8000`

The server also recognizes the existing environment variable names already present in this project, so it works without changing your current local configuration.
