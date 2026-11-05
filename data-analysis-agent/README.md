# Lens — AI Data Analysis Agent

A provider-neutral FastAPI workspace for profiling CSV/Excel datasets and asking grounded analysis questions using the LLM already configured in `.env`.

## Run locally

```powershell
python -m pip install -r requirements.txt
python -m uvicorn app:app --reload
```

Open `http://127.0.0.1:8000`.

The app reads `LLM_API_KEY`, `LLM_MODEL`, and `LLM_BASE_URL` from `.env`. Uploaded datasets are kept only in process memory and are cleared when the server restarts.
