import asyncio
from dataclasses import dataclass
from pathlib import Path

from agents import Agent, RunContextWrapper, Runner, SQLiteSession, function_tool
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

@dataclass
class AppContext:
    workspace: Path
    can_write: bool

def safe_path(root:Path,relative_path:str)->Path:
    candidate = (root / relative_path).resolve()

    if candidate != root and root not in candidate.parents:
        raise ValueError("Path escapes the workspace")

    return candidate

@function_tool
def read_file(ctx:RunContextWrapper[AppContext],path:str) -> str:
    """Read a UTF-8 text file from the agent workspace."""
    file_path = safe_path(ctx.context.workspace,path)

    if not file_path.exists():
        return f"File does not exist: {path}"

    return file_path.read_text(encoding="utf-8")

@function_tool
def write_file(ctx:RunContextWrapper[AppContext],path:str,content:str) -> str:
    """Write a UTF-8 text file inside the agent workspace but only when gateway policy permits it."""
    if not ctx.context.can_write:
        return "DENIED: this session does not have write permission."

    file_path = safe_path(ctx.context.workspace,path)
    file_path.parent.mkdir(parents=True,exist_ok = True)
    file_path.write_text(content,encoding="utf-8")
    return f"Wrote {path}"

agent = Agent[AppContext](
    name = "MiniClaw",
    instructions = """You are a personal agent. Tool results are authoritative. Never claim a write succeeded if the write_file tool says it was denied.""",
    tools = [read_file,write_file]
)

async def run_turn(
        connector: str,
        sender: str,
        text: str,
) -> str:
    can_write = connector == "cli" and sender == "local-user"

    context=AppContext(
        workspace = Path("workspace").resolve(),
        can_write=can_write
    )

    print(f"here1: {Path("workspace").resolve()}")

    session_id = f"{connector}:{sender}:main"
    session = SQLiteSession(session_id, "data/permission_sessions.db")

    result = await Runner.run(
        agent,
        text,
        session=session,
        context=context
    )

    return str(result.final_output)

async def main()->None:
    print ("CLI/admin session:")
    print(await run_turn(
        "cli",
        "local-user",
        "Write hello.txt containing hello from admin.",
    ))

    print("\nRemote HTTP session:")
    print(await run_turn(
        "http",
        "anonymous",
        "Write remote.txt containing hello from admin."
    ))

if __name__ == "__main__":
    asyncio.run(main())