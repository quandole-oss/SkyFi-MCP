# Using SkyFi MCP with LangChain

Integrate SkyFi satellite imagery tools into a LangChain agent using the `langchain-mcp-adapters` package.

## Prerequisites

- Python 3.11+
- Your SkyFi API key from [app.skyfi.com/settings/api](https://app.skyfi.com/settings/api)
- An LLM API key (OpenAI, Anthropic, or other LangChain-supported provider)

## Install Dependencies

```bash
pip install langchain langchain-mcp-adapters langchain-openai langgraph mcp
```

## Setup

The `langchain-mcp-adapters` package provides `load_mcp_tools()` which connects to an MCP server, discovers its tools, and converts them into LangChain `BaseTool` instances.

### Basic Agent

```python
"""LangChain agent with SkyFi MCP tools."""

import asyncio
import os

from langchain_mcp_adapters.tools import load_mcp_tools
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

SKYFI_API_KEY = os.environ["SKYFI_API_KEY"]


async def main():
    server_params = StdioServerParameters(
        command="uvx",
        args=["skyfi-mcp"],
        env={"SKYFI_API_KEY": SKYFI_API_KEY},
    )

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # Load all 21 SkyFi tools as LangChain tools
            tools = await load_mcp_tools(session)
            print(f"Loaded {len(tools)} tools")

            # Create a ReAct agent
            llm = ChatOpenAI(model="gpt-4o")
            agent = create_react_agent(llm, tools)

            # Run a query
            result = await agent.ainvoke(
                {
                    "messages": [
                        {
                            "role": "user",
                            "content": (
                                "Search for recent high-resolution optical imagery "
                                "of Lake Tahoe with less than 15% cloud cover. "
                                "Then estimate the price for the best result."
                            ),
                        }
                    ]
                }
            )

            # Print the final response
            for msg in result["messages"]:
                if hasattr(msg, "content") and msg.content:
                    print(f"\n[{msg.type}]: {msg.content}")


if __name__ == "__main__":
    asyncio.run(main())
```

### Run

```bash
export OPENAI_API_KEY="sk-..."
export SKYFI_API_KEY="your-skyfi-key"
python langchain_skyfi_agent.py
```

## Interactive Conversation Agent

For a multi-turn interactive session:

```python
"""Interactive LangChain agent with SkyFi MCP tools."""

import asyncio
import os

from langchain_mcp_adapters.tools import load_mcp_tools
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

SKYFI_API_KEY = os.environ["SKYFI_API_KEY"]


async def main():
    server_params = StdioServerParameters(
        command="uvx",
        args=["skyfi-mcp"],
        env={"SKYFI_API_KEY": SKYFI_API_KEY},
    )

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await load_mcp_tools(session)

            llm = ChatOpenAI(model="gpt-4o")
            agent = create_react_agent(llm, tools)

            messages = []
            print("SkyFi + LangChain Agent (type 'quit' to exit)")
            print("-" * 50)

            while True:
                user_input = input("\nYou: ").strip()
                if user_input.lower() in ("quit", "exit"):
                    break

                messages.append({"role": "user", "content": user_input})

                result = await agent.ainvoke({"messages": messages})
                messages = result["messages"]

                # Print the last AI message
                for msg in reversed(result["messages"]):
                    if hasattr(msg, "content") and msg.content and msg.type == "ai":
                        print(f"\nAssistant: {msg.content}")
                        break


if __name__ == "__main__":
    asyncio.run(main())
```

## Using with the Remote Server

To connect to the remote MCP server instead of the local stdio server, use the Streamable HTTP transport:

```python
from mcp.client.streamable_http import streamablehttp_client

async with streamablehttp_client(
    url="https://skyfi-mcp.your-domain.workers.dev/mcp",
    headers={"Authorization": "Bearer your-api-key"},
) as (read, write, _):
    async with ClientSession(read, write) as session:
        await session.initialize()
        tools = await load_mcp_tools(session)
        # ... use tools with your agent
```

## Using with Anthropic Claude

Swap `ChatOpenAI` for `ChatAnthropic`:

```python
from langchain_anthropic import ChatAnthropic

llm = ChatAnthropic(model="claude-sonnet-4-20250514")
agent = create_react_agent(llm, tools)
```

## First Search

```
You: Find satellite imagery of the Suez Canal from the last month.

[tool call: geocode("Suez Canal")]
[tool call: search_archive(location=..., date_range=...)]

Assistant: I found 15 satellite images of the Suez Canal from the past month.
Here are the top 3 by resolution:
1. img-suez001 | Maxar | 0.3m | 2026-03-05 | 3% cloud cover
2. img-suez002 | Airbus | 0.5m | 2026-02-28 | 8% cloud cover
3. img-suez003 | Planet | 3.0m | 2026-03-10 | 0% cloud cover
```

## Troubleshooting

| Issue | Fix |
|-------|-----|
| `ModuleNotFoundError: langchain_mcp_adapters` | Install it: `pip install langchain-mcp-adapters` |
| Tools list is empty | Ensure `uvx skyfi-mcp` starts without errors; check `SKYFI_API_KEY` is set |
| Agent loops without answering | Try a different LLM model or simplify the query |
| `Connection refused` on remote | Verify the remote server URL and authentication |
