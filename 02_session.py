import asyncio

from agents import Agent, Runner, trace, SQLiteSession
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

agent = Agent(
    name = "MiniClaw",
    instructions = ("""
You are a concise personal assistant.     
"""),
)

session=SQLiteSession("main","data/conversations.db")

async def main() -> None:
    print("MiniClaw runtime. Type 'quit' to stop.\n")

    with trace("MiniClaw 01"):
        while True:
            text = input("you> ").strip()

            if text.lower() in {"quit", "exit"}:
                break

            result = await Runner.run(agent,text,session=session)
            print(f"claw> {result.final_output}\n")

if __name__ == "__main__":
    asyncio.run(main())