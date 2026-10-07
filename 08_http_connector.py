import asyncio
import json

from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from queue import Queue

from threading import Thread
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

@dataclass
class PendingRequest:
    message: IncomingMessage
    reply_queue: Queue[str]


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

INBOX: Queue[PendingRequest] = Queue()

class WebhookHandler(BaseHTTPRequestHandler):
    def do_POST(self)->None:
        if self.path != "/message":
            self.send_error(404)
            return

        length = int(self.headers.get("Content-Length","0"))
        raw_body = self.rfile.read(length)

        try:
            body = json.loads(raw_body.decode("utf-8"))

            message = IncomingMessage(
                connector = "http",
                sender = str(body["sender"]),
                thread = str(body.get("thread","main")),
                text=str(body["text"]),
            )

        except (json.JSONDecodeError,KeyError,TypeError) as exc:
            self.send_response(400)
            self.send_header("Content-Type","application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error":str(exc)}).encode("utf-8"))
            return

        reply_queue: Queue[str] = Queue(maxsize=1)
        INBOX.put(PendingRequest(message,reply_queue))

        try:
            reply = reply_queue.get(timeout=1200)
        except Exception:
            self.send_response(504)
            self.end_headers()
            return

        payload = json.dumps({"reply":reply}).encode("utf-8")

        self.send_response(200)
        self.send_header("Content-Type","application/json")
        self.send_header("Content-Length",str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self,format:str,*args)->None:
        return

def start_http_server() -> None:
    server = ThreadingHTTPServer(("127.0.0.1",8080),WebhookHandler)
    print("HTTP connector listening at http://127.0.0.1:8080/message")
    server.serve_forever()

async def gateway_pump(gateway: Gateway)->None:
    while True:
        pending = await asyncio.to_thread(INBOX.get)

        try:
            answer = await gateway.handle(pending.message)
        except Exception as exc:
            answer= f"Gateway error: {type(exc).__name__}: {exc}"
        pending.reply_queue.put(answer.text)


async def main() -> None:
    runtime = AgentRuntime()
    gateway = Gateway(runtime,"data/https_sessions.db")

    Thread(target=start_http_server,daemon=True).start()
    await gateway_pump(gateway)

if __name__ == "__main__":
    asyncio.run(main())