import asyncio
from dataclasses import dataclass 

from agents import Agent,Runner,RunContextWrapper,function_tool
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

@dataclass
class UserContext:
    name:str
    age:int

@function_tool
def get_user_age(ctx:RunContextWrapper[UserContext]) -> str:
    return f"{ctx.context.name} is {ctx.context.age} years old."

agent = Agent[UserContext](
    name=  "Assistant",
    instructions = "Help the user. Use your tools when appropriate.",
    tools = [get_user_age]
)

async def main():

    user = UserContext(name = "Zeeshan",age=40)

    result = await Runner.run(
        agent,
        "How old am I?",
        context=user
    )

    print(result.final_output)

asyncio.run(main())
