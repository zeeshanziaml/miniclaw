import asyncio

from pathlib import Path
from agents import Agent, Runner, trace, SQLiteSession, function_tool
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

WORKSPACE = Path("workspace").resolve()
WORKSPACE.mkdir(exist_ok=True)

def safe_path(relative_path:str)->Path:
    candidate = (WORKSPACE / relative_path).resolve()

    if candidate != WORKSPACE and WORKSPACE not in candidate.parents:
        raise ValueError("Path escapes the workspace")

    return candidate

@function_tool
def list_files() -> str:
    """List files in the agent workspace."""
    files = [
        str(path.relative_to(WORKSPACE))
        for path in WORKSPACE.rglob("*")
        if path.is_file()
    ]

    if not files:
        return "Workspace is empty"

    return "\n".join(sorted(files))

@function_tool
def read_file(path:str) -> str:
    """Read a UTF-8 text file from the agent workspace."""
    file_path = safe_path(path)

    if not file_path.exists():
        return f"File does not exist: {path}"

    return file_path.read_text(encoding="utf-8")

@function_tool
def write_file(path:str,content:str) -> str:
    """Write a UTF-8 text file inside the agent workspace."""
    file_path = safe_path(path)
    file_path.parent.mkdir(parents=True,exist_ok = True)
    file_path.write_text(content,encoding="utf-8")
    return f"Wrote {path}"

agent = Agent(
    name = "MiniClaw",
    instructions = ("""
You are a personal assistant with a local workspace.
Use tools when the user asks you to inspect or modify workspace files.     
"""),
    tools = [list_files,read_file,write_file]
)

session=SQLiteSession("main","data/conversations.db")

async def main() -> None:
    print("MiniClaw runtime. Type 'quit' to stop.\n")

    with trace("MiniClaw w/ Workspace"):
        while True:
            text = input("you> ").strip()

            if text.lower() in {"quit", "exit"}:
                break

            result = await Runner.run(agent,text,session=session)
            print(f"claw> {result.final_output}\n")

if __name__ == "__main__":
    asyncio.run(main())