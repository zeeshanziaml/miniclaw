import asyncio

from dataclasses import dataclass
from pathlib import Path
from agents import Agent, Runner, trace, SQLiteSession, function_tool, RunContextWrapper
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

WORKSPACE = Path("workspace").resolve()
WORKSPACE.mkdir(exist_ok=True)

@dataclass
class AppContext:
    workspace: Path
    config_dir: Path

def safe_path(root:Path,relative_path:str)->Path:
    candidate = (root / relative_path).resolve()

    if candidate != root and root not in candidate.parents:
        raise ValueError("Path escapes the workspace")

    return candidate


def load_configuration(config_dir:Path) -> str:
    pieces: list[str] = []

    for name in ["USER.md","SOUL.md", "AGENTS.md","TOOLS.md"]:
        path = config_dir / name
        if path.exists():
            pieces.append(path.read_text(encoding="utf-8"))

    return "\n\n---\n\n".join(pieces)

def dynamic_instructions(
        ctx:RunContextWrapper[AppContext],
        agent: Agent[AppContext],
) -> str:
    del agent
    return ("You are a MiniClaw, a local personal agent.\n\n" + load_configuration(ctx.context.config_dir))

@function_tool
def list_files(ctx:RunContextWrapper[AppContext]) -> str:
    """List files in the agent workspace."""
    root = ctx.context.workspace
    files = [
        str(path.relative_to(root))
        for path in root.rglob("*")
        if path.is_file()
    ]

    if not files:
        return "Workspace is empty"

    return "\n".join(sorted(files))

@function_tool
def read_file(ctx:RunContextWrapper[AppContext],path:str) -> str:
    """Read a UTF-8 text file from the agent workspace."""
    file_path = safe_path(ctx.context.workspace,path)

    if not file_path.exists():
        return f"File does not exist: {path}"

    return file_path.read_text(encoding="utf-8")

@function_tool
def write_file(ctx:RunContextWrapper[AppContext],path:str,content:str) -> str:
    """Write a UTF-8 text file inside the agent workspace."""
    file_path = safe_path(ctx.context.workspace,path)
    file_path.parent.mkdir(parents=True,exist_ok = True)
    file_path.write_text(content,encoding="utf-8")
    return f"Wrote {path}"

app_context = AppContext(
    workspace=Path("workspace").resolve(),
    config_dir=Path("config").resolve(),
)

agent = Agent[AppContext](
    name = "MiniClaw",
    instructions = dynamic_instructions,
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

            result = await Runner.run(agent,text,session=session,context=app_context)
            print(f"claw> {result.final_output}\n")

if __name__ == "__main__":
    asyncio.run(main())