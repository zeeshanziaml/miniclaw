import asyncio
import sqlite3
import time
from dataclasses import dataclass

from agents import (
    Agent,
    RunContextWrapper,
    Runner,
    SQLiteSession,
    function_tool,
)
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

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

@dataclass
class AppContext:
    session_id: str
    cron: CronStore

@function_tool
def schedule_message(ctx:RunContextWrapper[AppContext], delay_seconds:int, message:str)->str:
    """Schedule a message to this same session after a delay in seconds."""
    if delay_seconds < 1:
        return "delay_seconds must be atleast 1"

    job_id = ctx.context.cron.add(ctx.context.session_id, delay_seconds, message)
    return f"Scheduled job {job_id}."

class Gateway:
    def __init__(self)->None:
        self.cron = CronStore("data/cron.db")
        self.agent = Agent[AppContext](
            name="MiniClaw",
            instructions="""
            You are a concise personal agent.
            If the user explicitly asks you to remind them after a delay,
            use schedule_message.
            """,
            tools = [schedule_message],
        )

    async def run_session(self, session_id:str, text:str)->str:
        session = SQLiteSession(session_id,"data/cron_sessions.db")
        context= AppContext(session_id,self.cron)

        result = await Runner.run(self.agent,text,session=session,context=context)
        return str(result.final_output)

    async def cron_loop(self) -> None:
        while True:
            for job_id, session_id, message in self.cron.claim_due():
                try: 
                    answer = await self.run_session(
                        session_id,
                        "[SCHEDULED EVENT]\n" + message,
                    )
                    print(f"\n[cron -> {session_id}] {answer}\n")
                    self.cron.mark_done(job_id)
                except Exception as exc:
                    print(f"cron job {job_id} failed: {exc}")
            await asyncio.sleep(1)

async def interactive_loop(gateway: Gateway) -> None:
    session_id = "cli:local-user:main"

    while True:
        text = await asyncio.to_thread(input,"you> ")
        text = text.strip()

        if text.lower() in {"quit","exit"}:
            return

        answer = await gateway.run_session(session_id,text)
        print(f"claw> {answer}\n")

async def main() -> None:
    gateway = Gateway()

    await asyncio.gather(
        interactive_loop(gateway),
        gateway.cron_loop()
    )

if __name__ == "__main__":
    asyncio.run(main())