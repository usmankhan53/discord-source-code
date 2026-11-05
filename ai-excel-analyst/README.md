# Sheetwise — AI Excel Analyst

A FastAPI + pandas spreadsheet analyst with a responsive Tailwind CSS interface and streamed AI explanations.

## Run

From this directory:

```powershell
python -m pip install -r requirements.txt
python -m uvicorn app:app --reload
```

Open http://127.0.0.1:8000. Set `OXYY_API_KEY`, `LLM_BASE_URL` (defaults to `https://api.oxyy.ai/v1`), and `LLM_MODEL` in `.env`. Keep credentials out of source control. Tailwind loads from its CDN, so the interface needs internet access for styling.

Upload an `.xlsx` workbook (up to 5 MB / 10,000 rows). The first worksheet is used. Ask for row counts, totals, averages, minimums, maximums, grouped totals or averages, top/bottom five, and unique values. Suggested questions adapt to the uploaded columns.

## Streaming

`POST /ask/stream` accepts `{"question":"What is the total Revenue?"}` and returns newline-delimited JSON events:

- `status`: progress text in `message`.
- `result`: the pandas calculation in `answer` and selected `operation`.
- `delta`: actual provider-generated explanation text in `text`.
- `done`: successful completion.
- `error`: a readable failure in `message`, including errors after streaming begins.

The browser decodes split UTF-8/chunk boundaries, renders each delta, detects interrupted responses, and supports stopping the fetch. Completed calculations remain visible if explanation generation fails. The existing `POST /ask` JSON endpoint is retained.

The model chooses from a fixed list of operations; pandas performs the calculation. No generated Python is executed. A second provider request streams an explanation of the result. Column names/types and the limited calculation result are sent to the configured AI provider.

This remains a single-user, in-memory app: uploads replace the current workbook and are lost on restart. Use one worker. Separate user sessions and persistent storage are needed before deploying a shared service.

## Verify

```powershell
python -m unittest discover -v
node --check static/app.js
```

The regression suite mocks the AI provider and covers valid/invalid uploads, calculations, streaming success/failure, input validation, and the legacy endpoint.
