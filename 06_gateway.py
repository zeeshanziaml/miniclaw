import asyncio

from dataclasses import dataclass
from pathlib import Path
from agents import Agent, Runner, trace, SQLiteSession, function_tool, RunContextWrapper
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

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

class AgentRuntime:
    def __init__(self) -> None:
        self.agent = Agent(
            name = "MiniClaw",
            instructions = (
                """
                You are a concise personal assistant. 
                Treat each session as an independent conversation.
"""
            )
        )

    async def run_turn(
            self,
            text:str,
            session: SQLiteSession) -> str:
        result = await Runner.run(
            self.agent,
            text,
            session=session,
        )
        return str(result.final_output)

class Gateway:
    def __init__(self,runtime:AgentRuntime,db_path:str) -> None:
        self.runtime = runtime
        self.db_path = db_path

    def session_id_for(self,message: IncomingMessage) -> str:
        return f"{message.connector}: {message.sender}: {message.thread}"
    
    async def handle(self,message:IncomingMessage) -> OutgoingMessage:
        session_id = self.session_id_for(message)
        session=SQLiteSession(session_id,self.db_path)

        answer = await self.runtime.run_turn(
            message.text,
            session,
        )

        return OutgoingMessage(
            connector=message.connector,
            thread=message.thread,
            text=answer,
        )

async def main() -> None:
    Path("data").mkdir(exist_ok=True)

    runtime = AgentRuntime()
    gateway = Gateway(runtime, "data/gateway_sessions.db")

    alice = IncomingMessage(
        connector = "demo",
        sender=  "alice",
        thread = "main",
        text = "My favorite animal is the red panda."
    )

    bob = IncomingMessage(
        connector = "demo",
        sender = "bob",
        thread = "main",
        text = "My favorite animal is the octopus."
    )

    print((await gateway.handle(alice)).text)
    print((await gateway.handle(bob)).text)

    print((
        await gateway.handle(
            IncomingMessage("demo","alice","main","what animal do I like?")
        )
    ).text)

    print((
        await gateway.handle(
            IncomingMessage("demo","bob","main","what animal do I like?")
        )
    ).text)

if __name__ == "__main__":
    asyncio.run(main())