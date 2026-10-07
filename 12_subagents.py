import asyncio
from agents import Agent, Runner, SQLiteSession, trace
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

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
    instructions = """
    You are the main personal agent.
    Handle simple requests yourself.
    Delegate research-shaped tasks to the research specialist and 
    implementation planning tasks to the planning specialist.
    """,
    tools = [
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

async def main() -> None:
    session = SQLiteSession("main","data/subagent_sessions.db")
    with trace("MiniClaw Subagents"):
        result = await Runner.run(
            main_agent,"I want to add a real Gmail connector to MiniClaw. What should I think through before implementing it?",
            session=session
        )
        print(result.final_output)

if __name__ == "__main__":
    asyncio.run(main())
