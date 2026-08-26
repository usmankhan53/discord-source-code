# Navigator

A local AI browser automation workspace with a FastAPI backend and a responsive Tailwind CSS interface. Give the agent a goal, optionally choose a starting URL, and watch its browser steps and screenshots stream into the UI.

## Features

- Goal-driven browser planning with the LLM already configured in `.env`
- Live Chromium automation through Playwright
- Server-sent activity, browser snapshots, stop controls, and final summaries
- Generic OpenAI-compatible chat-completions client with no provider UI branding
- Local run history stored in the browser
- Public-URL guardrails and confirmation boundaries for high-impact actions

## Run locally

```powershell
python -m pip install -r requirements.txt
python -m playwright install --no-shell chromium
python -m uvicorn app:app --reload
```

Open `http://127.0.0.1:8000`.

## Configuration

The app automatically uses the compatible model settings already present in `.env`. For a fresh setup, copy `.env.example` to `.env` and set:

```dotenv
LLM_API_KEY=your_api_key_here
LLM_MODEL=your_model_name
LLM_BASE_URL=https://your-llm-endpoint.example/v1
```

The configured endpoint must support the `/chat/completions` request shape. Keep `.env` private; it is already ignored by Git.

## Safety scope

The agent blocks local/private network URLs and will not complete purchases, payments, account/data deletion, messages, uploads, CAPTCHAs, or security-setting changes. Those actions require a separate user-confirmed workflow.
