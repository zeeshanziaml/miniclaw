import asyncio
import re
import sqlite3
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from agents import Agent, RunContextWrapper, Runner,SQLiteSession,function_tool

from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

WORKSPACE = Path("workspace").resolve()
DATA_DIR = Path("data")
CONFIG_DIR = Path("config").resolve()
SKILLS_DIR = Path("skills").resolve()

HEARTBEAT_INTERVAL_SECONDS = 30

for directory in [DATA_DIR,WORKSPACE,CONFIG_DIR,SKILLS_DIR]:
    directory.mkdir(parents=True,exist_ok=True)


@dataclass(frozen=True)
class IncomingMessage:
    connector: str
    sender: str
    thread: str
    text: str

@dataclass(frozen=True)
class OutgoingMessage:
    connector: str
    thread:str
    text:str

class MemoryStore:
    def __init__(self,db_path:str)-> None:
        self.db_path = db_path

        with sqlite3.connect(self.db_path) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    source_session TEXT NOT NULL,
                    text TEXT NOT NULL
                )
                """
            )

    def add(self,source_session:str, text:str)-> int:
        with sqlite3.connect(self.db_path) as connection:
            cursor = connection.execute(
                "INSERT INTO memories(source_session, text) VALUES (?,?)",
                (source_session,text),
            )
            return int(cursor.lastrowid)

    def search(self,query:str, limit:int=5)-> list[str]:
        query_terms = set(re.findall(r"[a-z0-9]+",query.lower()))

        if not query_terms:
            return []
        
        with sqlite3.connect(self.db_path) as connection:
            rows = connection.execute(
                "SELECT id, created_at, source_session, text FROM memories ORDER by id DESC LIMIT 500"
            ).fetchall()

        scored: list[tuple[int,tuple]] = []

        for row in rows:
            text_terms = set(re.findall(r"[a-z0-9]+",row[3].lower()))
            score = len(query_terms & text_terms)
            if score:
                scored.append((score,row))

        scored.sort(key=lambda item: (item[0], item[1][0]), reverse=True)


        return [
            f"[{row[0]}] {row[1]} | {row[2]} | {row[3]}"
                for _, row in scored[:limit]
        ]

class CronStore:
    def __init__(self,db_path:str)->None:
        self.db_path = db_path

        with sqlite3.connect(self.db_path) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS jobs(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    due_at REAL NOT NULL,
                    session_id TEXT NOT NULL,
                    message TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending'
                )
                """
            )

    def add(self,session_id:str, delay_seconds:int, message:str) -> int:
        due_at = time.time() + delay_seconds

        with sqlite3.connect(self.db_path) as connection:
            cursor = connection.execute(
                "INSERT INTO jobs(due_at, session_id, message) VALUES (?,?,?)", (due_at,session_id,message),
            )
            return int(cursor.lastrowid)

    def claim_due(self)-> list[tuple[int,str,str]]:
        now = time.time()

        with sqlite3.connect(self.db_path) as connection:
            rows = connection.execute(
                "SELECT id, session_id, message FROM jobs WHERE status='pending' AND due_at <= ? ORDER BY due_at", (now,),
            ).fetchall()

            ids = [row[0] for row in rows]

            if ids:
                placeholders = ",".join("?" for _ in ids)
                connection.execute(
                    f"UPDATE jobs SET status='running' WHERE id IN ({placeholders})",ids,
                )

        return [(int(row[0]), str(row[1]), str(row[2])) for row in rows]

    def mark_done(self,job_id:int)->None:
        with sqlite3.connect(self.db_path) as connection:
            connection.execute(
                "UPDATE jobs SET status='done' WHERE id=?",(job_id,),
            )

    def mark_pending(self,job_id:int)->None:
        with sqlite3.connect(self.db_path) as connection:
            connection.execute(
                "UPDATE jobs SET status='pending' WHERE id=?",(job_id,),
            )

@dataclass
class AppContext:
    session_id: str
    connector: str
    can_write: bool
    workspace: Path
    config_dir: Path
    skills_dir: Path
    memory: MemoryStore
    cron: CronStore

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

def skill_metadata(path:Path) -> tuple[str,str]:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()

    name = path.parent.name
    description = ""

    if lines and lines[0].strip() == "---":
        for line in lines[1:]:
            if line.strip() == "---":
                break

            key,separator,value = line.partition(":")
            if not separator:
                continue

            if key.strip() == "name":
                name = value.strip()
            elif key.strip() == "description":
                description=value.strip()

    return name,description 

def skill_catalog(skills_dir:Path)->str:
    entries: list[str] = []

    for path in sorted(skills_dir.glob("*/SKILL.md")):
        name,description = skill_metadata(path)
        entries.append(f"- {name}: {description}")

    return "\n".join(entries) if entries else "- No skills installed"

def dynamic_instructions(ctx: RunContextWrapper[AppContext], agent: Agent[AppContext])->str:
    del agent
    permissions = "write-enabled" if ctx.context.can_write else "read-only"
    return (
    """
    You are MiniClaw, a small persistent personal agent.\n
    Use tools for real environment state; never invent tool success.\n
    When the user explicitly asks to remember/save a durable fact, call remember.\n
    Before claiming knowledge from another session or older work, call search_memory.\n
    If a skill clearly matches the task, call load_skill before doing that task.\n
    """ +
    f"This session is {permissions}.\n\n"
    + load_configuration(ctx.context.config_dir)
    + "\n\n# Installed skills\n"
    + skill_catalog(ctx.context.skills_dir)
    )

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
    """Write a UTF-8 text file inside the agent workspace but only when gateway policy permits it."""
    if not ctx.context.can_write:
        return "DENIED: this session does not have write permission."

    file_path = safe_path(ctx.context.workspace,path)
    file_path.parent.mkdir(parents=True,exist_ok = True)
    file_path.write_text(content,encoding="utf-8")
    return f"Wrote {path}"

@function_tool
def current_date() -> str:
    """Return the local machine's current calendar date as YYYY-MM-DD."""
    return date.today().isoformat()

@function_tool
def load_skill(
    ctx:RunContextWrapper[AppContext],
    name: str,
) -> str:
    """Load the full instructions for a named skill."""
    path = ctx.context.skills_dir / name / "SKILL.md"

    if not path.exists():
        return f"Unknown skill: {name}"
    return path.read_text(encoding="utf-8")

@function_tool
def remember(ctx: RunContextWrapper[AppContext],text:str)->str:
    """Store a durable fact, decision, preference, or useful note."""
    memory_id = ctx.context.memory.add(ctx.context.session_id,text)
    return f"Stored memory {memory_id}."

@function_tool
def search_memory(ctx:RunContextWrapper[AppContext],query:str)->str:
    """Search durable memories from all sessions."""
    results = ctx.context.memory.search(query)
    return "\n".join(results) if results else "No matching memories"

@function_tool
def schedule_message(ctx:RunContextWrapper[AppContext], delay_seconds:int, message:str)->str:
    """Schedule a message to this same session after a delay in seconds."""
    if delay_seconds < 1:
        return "delay_seconds must be atleast 1"

    job_id = ctx.context.cron.add(ctx.context.session_id, delay_seconds, message)
    return f"Scheduled job {job_id}."

research_agent = Agent(
    name = "Research Specialist",
    instructions= """
                    You are a careful research specialist
                    Break a research question into evidence needed, uncertainties, and a concise conclusion.
                """,
)

planning_agent = Agent(
    name = "Planning Specialist",
    instructions = """
                    You are a planning specialist.
                    Turn a goal into a short ordered implementation plan with clear checkpoints.
                    """
)

main_agent = Agent(
    name = "MiniClaw",
    instructions = dynamic_instructions,
    tools = [list_files,
             read_file,
             write_file,
             current_date,
             load_skill,
             remember,
             search_memory,
             schedule_message,
            research_agent.as_tool(
                tool_name = "delegate_research",
                tool_description="Delegate a bounded research question."
            ),
            planning_agent.as_tool(
                tool_name="delegate_planning",
                tool_description="Delegate an implementation planning task."
            ),
    ],
)

class AgentRuntime:
    async def run_turn(
            self,
            text:str,
            session: SQLiteSession,
            context: AppContext) -> str:
        result = await Runner.run(
            main_agent,
            text,
            session=session,
            context=context,
        )
        return str(result.final_output)

class Gateway:
    def __init__(self) -> None:
        self.runtime = AgentRuntime()
        self.memory = MemoryStore("data/memory.db")
        self.cron = CronStore("data/cron.db")
        self._session_locks: dict[str,asyncio.Lock] = {}

    @staticmethod
    def session_id_for(message: IncomingMessage) -> str:
        return f"{message.connector}: {message.sender}: {message.thread}"

    @staticmethod
    def can_write_for(message:IncomingMessage)->bool:
        return message.connector == "cli" and message.sender == "local-user"

    def lock_for(self,session_id:str)->asyncio.Lock:
        lock = self._session_locks.get(session_id)
        if lock is None:
            lock = asyncio.Lock()
            self._session_locks[session_id] = lock
        return lock

    def context_for(self,session_id:str, connector:str,can_write:bool)->AppContext:
        return AppContext(
            session_id=session_id,
            connector=connector,
            can_write=can_write,
            workspace=WORKSPACE,
            config_dir=CONFIG_DIR,
            skills_dir=SKILLS_DIR,
            memory=self.memory,
            cron=self.cron,
        )

    async def run_session(self,session_id:str, text:str, connector:str, can_write:bool)-> str:
        session = SQLiteSession(session_id,"data/sessions.db")
        context = self.context_for(session_id,connector,can_write)

        async with self.lock_for(session_id):
            return await self.runtime.run_turn(text,session,context)

    async def handle(self,message:IncomingMessage) -> OutgoingMessage:
        session_id = self.session_id_for(message)

        answer = await self.run_session(
            session_id=session_id,
            text=message.text,
            connector = message.connector,
            can_write = self.can_write_for(message),
        )
        return OutgoingMessage(message.connector,message.thread,answer)

    async def cron_loop(self) -> None:
        while True:
            for job_id, session_id, message in self.cron.claim_due():
                connector = session_id.split(":",1)[0]
                try: 
                    answer = await self.run_session(
                        session_id=session_id,
                        text="[SCHEDULED EVENT]\n" + message,
                        connector=connector,
                        can_write=(connector=="cli")
                    )
                    print(f"\n[cron -> {session_id}] {answer}\n")
                    self.cron.mark_done(job_id)
                except Exception as exc:
                    self.cron.mark_pending(job_id)
                    print(f"cron job {job_id} failed: {exc}")
            await asyncio.sleep(1)

    async def heartbeat_loop(self) -> None:
        heartbeat_path = CONFIG_DIR / "HEARTBEAT.md"
        while True:
            await asyncio.sleep(HEARTBEAT_INTERVAL_SECONDS)
            if not heartbeat_path.exists():
                continue

            checklist = heartbeat_path.read_text(encoding="utf-8")
            answer = await self.run_session(
                session_id = "system:heartbeat",
                text="[HEARTBEAT]\n\n" + checklist,
                connector="system",
                can_write=False,
            )

            if answer.strip() != "HEARTBEAT_OK":
                print(f"\n[heartbeat] {answer}\n")

class CLIConnector:
    def __init__(self,gateway:Gateway) -> None:
        self.gateway = gateway
        self.thread="main"

    async def run(self)-> None:
        print("MiniClaw CLI. Commands: /thread NAME, /quit\n")

        while True:
            text = (await asyncio.to_thread(input,f"you[{self.thread}]> ")).strip()
            if text.lower() in {"/quit","quit","exit"}:
                return

            if text.startswith("/thread"):
                new_thread = text.removeprefix("/thread").strip()
                if new_thread:
                    self.thread = new_thread
                    print(f"Switched to thread: {self.thread}\n")
                continue

            incoming = IncomingMessage(
                connector = "cli",
                sender="local-user",
                thread = self.thread,
                text=text
            )

            outgoing = await self.gateway.handle(incoming)
            print(f"claw> {outgoing.text}\n")

async def main() -> None:
    gateway = Gateway()
    connector = CLIConnector(gateway)

    await asyncio.gather(
        connector.run(),
        gateway.cron_loop(),
        gateway.heartbeat_loop()
    )

if __name__ == "__main__":
    asyncio.run(main())
