# Study Assistant

Local FastAPI study coach and a standard stdio MCP server. Both use the
configured LLM environment without provider branding.

## Web interface

```powershell
python -m pip install -r requirements.txt
python app.py
```

Open `http://127.0.0.1:8000`.

## Study workflows

- **Coach:** guided explanations and active-recall prompts.
- **Plan:** a generated task list that can be checked off in the browser.
- **Quiz:** multiple-choice questions whose answer key remains on the server until submission; the result is scored with explanations.
- **Cards:** flippable active-recall cards with an in-session known counter.

## MCP server

```powershell
python mcp_server.py
```

Configure an MCP client with command `python` and argument
`D:\\code\\project\\mcp_server.py`. Available tools: `ask_assistant`,
`study_topic`, and `model_ready`.
