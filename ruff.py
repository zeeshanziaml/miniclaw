import asyncio

from agents import Agent, Runner, trace, SQLiteSession
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

agent = Agent(
    name = "Assistant1",
    instructions = "You are a helper. Your name is Jarvis. Answer concisely",
)

async def main():

    with trace("SQLiteSession demo v2"):
        session = SQLiteSession("my_chat","memory.db")

        result = await Runner.run(agent,"My favorite programming language is FoxPro.", session=session)
        print(result.final_output)

        result = await Runner.run(agent,"What is my favorite programming language.", session=session)

        print(result.final_output)

asyncio.run(main())