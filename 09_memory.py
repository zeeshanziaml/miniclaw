import asyncio
import re
import sqlite3
from dataclasses import dataclass

from agents import (
    Agent,
    RunContextWrapper,
    Runner,
    SQLiteSession,
    function_tool
)
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

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

        with sqlite3.connect(self.db_path) as connection:
            rows = connection.execute(
                "SELECT id, created_at, source_session, text FROM memories ORDER by id DESC LIMIT 500"
            ).fetchall()

        scored: list[tuple[int,tuple]] = []

        for row in rows:
            text_terms = set(re.findall(r"[a-z0-9]+",row[3].lower()))
            score = len(query_terms & text_terms)
            if score > 0:
                scored.append((score,row))

        scored.sort(key=lambda item: (item[0], item[1][0]), reverse=True)

        results = []
        for score,row in scored[:limit]:
            memory_id, created_at, source_session, text = row
            results.append(
                f"[{memory_id}] {created_at} | {source_session} | {text}"
            )
        return results

@dataclass
class AppContext:
    session_id: str
    memory: MemoryStore

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

agent = Agent[AppContext](
    name = "MiniClaw",
    instructions = """
    You are a personal agent.
    Conversation history belongs to the current session.
    When the user explicitly asks to remember or save a durable fact,
    call remember. Before claiming to know a fact from older work or 
    another session, call search_memory.
    """,
    tools=[search_memory,remember],
)

memory_store = MemoryStore("data/memory.db")

async def run_session(session_id: str, text:str)->str:
    session = SQLiteSession(session_id,"data/memory_sessions.db")
    context = AppContext(session_id=session_id,memory=memory_store)

    result = await Runner.run(agent,text,session=session,context=context)
    return str(result.final_output)

async def main() -> None:
    print(await run_session("cli:main","Remember permanently that Project Finch uses a blue status light."))

    print(await run_session("http:other-thread","What do you know about Project Finch status light?"))


if __name__ == "__main__":
    asyncio.run(main())