# Using SkyFi MCP with Google ADK (Agent Development Kit)

Integrate SkyFi satellite imagery tools with Google's Agent Development Kit (ADK).

## Prerequisites

- Python 3.11+
- Google ADK installed
- A Gemini API key or Google Cloud credentials
- Your SkyFi API key from [app.skyfi.com/settings/api](https://app.skyfi.com/settings/api)

## Install Dependencies

```bash
pip install google-adk mcp
```

## Setup

Google ADK provides built-in MCP tool support through its `MCPToolset` class. This connects to the SkyFi MCP server and wraps all tools as ADK-compatible tools.

### Project Structure

```
skyfi_adk_agent/
    __init__.py
    agent.py
    .env
```

### agent.py

```python
"""SkyFi satellite imagery agent using Google ADK."""

import os

from google.adk.agents import Agent
from google.adk.tools.mcp_tool import MCPToolset, StdioServerParameters

SKYFI_API_KEY = os.environ["SKYFI_API_KEY"]


def create_agent() -> Agent:
    """Create an ADK agent with SkyFi MCP tools."""
    skyfi_tools = MCPToolset(
        connection_params=StdioServerParameters(
            command="uvx",
            args=["skyfi-mcp"],
            env={"SKYFI_API_KEY": SKYFI_API_KEY},
        )
    )

    agent = Agent(
        model="gemini-2.0-flash",
        name="skyfi_research_agent",
        description=(
            "A geospatial research assistant that can search, price, and order "
            "satellite imagery from SkyFi."
        ),
        instruction=(
            "You are a geospatial research assistant. Help users find and analyze "
            "satellite imagery using SkyFi tools.\n\n"
            "Guidelines:\n"
            "- Always geocode location names before searching\n"
            "- Present results in a clear, organized format\n"
            "- Show pricing before any order\n"
            "- NEVER auto-confirm orders -- always ask the user first\n"
            "- Explain sensor types when relevant (optical, SAR, multispectral)\n"
        ),
        tools=[skyfi_tools],
    )

    return agent


root_agent = create_agent()
```

### __init__.py

```python
from .agent import root_agent
```

### .env

```
SKYFI_API_KEY=your-skyfi-key
GEMINI_API_KEY=your-gemini-key
```

## Run the Agent

### With ADK CLI

```bash
cd skyfi_adk_agent
adk run .
```

### With ADK Web UI

```bash
adk web .
```

This launches a local web interface where you can chat with the agent.

### Programmatic Usage

```python
import asyncio
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from skyfi_adk_agent import root_agent


async def main():
    session_service = InMemorySessionService()
    runner = Runner(
        agent=root_agent,
        app_name="skyfi_demo",
        session_service=session_service,
    )

    session = await session_service.create_session(
        app_name="skyfi_demo", user_id="demo_user"
    )

    response = await runner.run(
        user_id="demo_user",
        session_id=session.id,
        new_message=types.Content(
            role="user",
            parts=[
                types.Part(
                    text="Find recent imagery of Mount Fuji with less than 10% cloud cover."
                )
            ],
        ),
    )

    for event in response:
        if event.content and event.content.parts:
            for part in event.content.parts:
                if part.text:
                    print(part.text)


if __name__ == "__main__":
    asyncio.run(main())
```

## Connecting to the Remote Server

To use the remote MCP server instead of the local stdio server, use `SseServerParams`:

```python
from google.adk.tools.mcp_tool import MCPToolset, SseServerParams

skyfi_tools = MCPToolset(
    connection_params=SseServerParams(
        url="https://skyfi-mcp.your-domain.workers.dev/sse",
        headers={"Authorization": "Bearer your-api-key"},
    )
)
```

## First Search

```
You: Search for multispectral imagery of the Nile Delta from the last 6 months.

  [calling geocode("Nile Delta")...]
  [calling search_archive(location=..., sensor_type=multispectral, date_range=...)]

Assistant: I found 22 multispectral images of the Nile Delta. Here are the top results:
1. img-nile001 | Maxar | 1.2m | 2026-02-15 | multispectral | 5% cloud cover
2. img-nile002 | Planet | 3.0m | 2026-01-20 | multispectral | 0% cloud cover
...
```

## Troubleshooting

| Issue | Fix |
|-------|-----|
| `ModuleNotFoundError: google.adk` | Install ADK: `pip install google-adk` |
| Tools not loading | Ensure `uvx skyfi-mcp` works in your terminal |
| `SKYFI_API_KEY is not set` | Add it to your `.env` file or export it |
| Agent does not call tools | Adjust the instruction prompt to be more explicit |
