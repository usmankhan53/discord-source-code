# Search Space

A private, provider-neutral AI search interface powered by FastAPI and Tailwind CSS.

## Run locally

1. Populate `LLM_API_KEY`, `LLM_MODEL`, and `LLM_BASE_URL` in `.env`.
2. Install dependencies: `pip install -r requirements.txt`
3. Start the app: `uvicorn app:app --reload`
4. Open `http://127.0.0.1:8000`

The LLM endpoint is expected to use the OpenAI-compatible chat-completions format.
