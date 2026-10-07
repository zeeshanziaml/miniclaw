import asyncio
from pathlib import Path
from dotenv import load_dotenv

from agents import Agent, Runner,SQLiteSession,function_tool
# Load environment variables from .env file
load_dotenv()

HEARTBEAT_INTERVAL_SECONDS = 30
HEARTBEAT_FILE = Path("config/HEARTBEAT.md")
WORKSPACE = Path("workspace").resolve()
RUN_LOCK = asyncio.Lock()

def safe_path(root:Path,relative_path:str)->Path:
    candidate = (root / relative_path).resolve()

    if candidate != root and root not in candidate.parents:
        raise ValueError("Path escapes the workspace")

    return candidate

@function_tool
def read_workspace_file(path: str) -> str:
    """Read a UTF-8 file from the workspace for inspection."""
    file_path = safe_path(WORKSPACE, path)

    if not file_path.exists():
        return f"File does not exist: {path}"

    return file_path.read_text(encoding="utf-8")

agent = Agent(
    name = "MiniClaw",
    instructions = (
        """
        You are a personal agent.
        A message beginning with [HEARTBEAT] is an automated poll.
        Use read_workspace_file when the checklist asks you to inspect a file.
        If nothing needs attention, reply exactly HEARTBEAT_OK.
        """
    ),
    tools = [read_workspace_file],
)

async def run_main_session(text:str)->str:
    session = SQLiteSession("main","data/heartbeat_sessions.db")
    async with RUN_LOCK:    
        result = await Runner.run(agent,text,session=session)

        return str(result.final_output)

async def heartbeat_loop() -> None:
    while True:
        await asyncio.sleep(HEARTBEAT_INTERVAL_SECONDS)

        checklist = HEARTBEAT_FILE.read_text(encoding="utf-8")
        answer = await run_main_session("[HEARTBEAT]\n\n" + checklist)

        if answer.strip() != "HEARTBEAT_OK":
            print(f"\n[heartbeat] {answer}\n")

async def interactive_loop() -> None:
    while True:
        text =  await asyncio.to_thread(input,"you> ")
        text = text.strip()

        if text.lower() in {"quit","exit"}:
            return

        answer = await run_main_session(text)
        print(f"claw> {answer}\n")


async def main() -> None:
    await asyncio.gather(
        interactive_loop(),
        heartbeat_loop(),
    )

if __name__ == "__main__":
    asyncio.run(main())