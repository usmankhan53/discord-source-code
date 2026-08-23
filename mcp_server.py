"""A stdio MCP server that provides access to the configured assistant."""
from mcp.server.fastmcp import FastMCP

from app import STUDY_INSTRUCTIONS, complete, settings

mcp = FastMCP("workspace-assistant")


@mcp.tool()
async def ask_assistant(prompt: str, instructions: str | None = None) -> str:
    """Ask the configured model a question and return its response."""
    return await complete(prompt, instructions)


@mcp.tool()
async def study_topic(topic: str, request: str, mode: str = "coach") -> str:
    """Tutor a subject, create a plan, quiz, or flashcards.

    Mode must be one of: coach, plan, quiz, flashcards.
    """
    if mode not in {"coach", "plan", "quiz", "flashcards"}:
        return "Mode must be coach, plan, quiz, or flashcards."
    return await complete(f"Topic: {topic}\nMode: {mode}\nLearner request: {request}", STUDY_INSTRUCTIONS)


@mcp.tool()
def model_ready() -> dict[str, bool]:
    """Check whether the model configuration is ready."""
    try:
        settings()
        return {"ready": True}
    except RuntimeError:
        return {"ready": False}


if __name__ == "__main__":
    mcp.run(transport="stdio")
