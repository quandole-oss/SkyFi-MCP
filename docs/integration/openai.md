# Using SkyFi MCP with OpenAI (ChatGPT & GPT API)

Integrate SkyFi satellite imagery tools with OpenAI's ChatGPT and the GPT API.

## Prerequisites

- OpenAI API key with access to GPT-4o or later
- A deployed SkyFi MCP remote server, or the local server running
- Your SkyFi API key from [app.skyfi.com/settings/api](https://app.skyfi.com/settings/api)
- Python 3.11+ for the bridge examples

## Approach

OpenAI does not natively speak MCP. There are two integration paths:

1. **MCP-to-OpenAI bridge** -- Use the `mcp` Python SDK as a client to connect to the SkyFi MCP server and expose its tools as OpenAI function-calling tools.
2. **Direct function calling** -- Map the SkyFi tool schemas to OpenAI's function-calling format manually.

Both approaches are shown below.

## Option A: MCP Bridge (Recommended)

This approach uses the `mcp` SDK to discover tools from the SkyFi server and translates them into OpenAI-compatible function definitions automatically.

### Install Dependencies

```bash
pip install openai mcp
```

### Bridge Script

```python
"""Bridge: SkyFi MCP tools -> OpenAI function calling."""

import asyncio
import json
import os

from openai import OpenAI
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]
SKYFI_API_KEY = os.environ["SKYFI_API_KEY"]


def mcp_tool_to_openai_function(tool) -> dict:
    """Convert an MCP tool definition to an OpenAI function schema."""
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description or "",
            "parameters": tool.inputSchema,
        },
    }


async def main():
    client = OpenAI(api_key=OPENAI_API_KEY)

    server_params = StdioServerParameters(
        command="uvx",
        args=["skyfi-mcp"],
        env={"SKYFI_API_KEY": SKYFI_API_KEY},
    )

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # Discover all tools
            tools_result = await session.list_tools()
            openai_tools = [
                mcp_tool_to_openai_function(t) for t in tools_result.tools
            ]

            # Conversation loop
            messages = [
                {
                    "role": "system",
                    "content": (
                        "You are a geospatial research assistant with access to "
                        "SkyFi satellite imagery tools. Help the user find, price, "
                        "and order satellite imagery. Never auto-confirm orders."
                    ),
                }
            ]

            print("SkyFi + OpenAI Bridge (type 'quit' to exit)")
            print("-" * 50)

            while True:
                user_input = input("\nYou: ").strip()
                if user_input.lower() in ("quit", "exit"):
                    break

                messages.append({"role": "user", "content": user_input})

                # Call OpenAI with tools
                response = client.chat.completions.create(
                    model="gpt-4o",
                    messages=messages,
                    tools=openai_tools,
                )

                choice = response.choices[0]

                # Handle tool calls in a loop
                while choice.finish_reason == "tool_calls":
                    messages.append(choice.message)

                    for tool_call in choice.message.tool_calls:
                        args = json.loads(tool_call.function.arguments)
                        print(f"  [calling {tool_call.function.name}...]")

                        result = await session.call_tool(
                            tool_call.function.name, arguments=args
                        )

                        tool_content = (
                            result.content[0].text
                            if result.content
                            else "{}"
                        )

                        messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": tool_call.id,
                                "content": tool_content,
                            }
                        )

                    response = client.chat.completions.create(
                        model="gpt-4o",
                        messages=messages,
                        tools=openai_tools,
                    )
                    choice = response.choices[0]

                print(f"\nAssistant: {choice.message.content}")
                messages.append(
                    {"role": "assistant", "content": choice.message.content}
                )


if __name__ == "__main__":
    asyncio.run(main())
```

### Run

```bash
export OPENAI_API_KEY="sk-..."
export SKYFI_API_KEY="your-skyfi-key"
python openai_skyfi_bridge.py
```

## Option B: Direct Function Calling

If you prefer not to run the MCP server, you can define the tool schemas directly and call the SkyFi API yourself. Here is an example for `search_archive`:

```python
import json
from openai import OpenAI

client = OpenAI()

tools = [
    {
        "type": "function",
        "function": {
            "name": "search_archive",
            "description": "Search SkyFi satellite imagery archive by location, date, and sensor.",
            "parameters": {
                "type": "object",
                "properties": {
                    "location": {
                        "type": "object",
                        "properties": {
                            "address": {"type": "string"},
                        },
                    },
                    "sensor_type": {
                        "type": "string",
                        "enum": ["optical", "sar", "multispectral", "hyperspectral"],
                    },
                    "cloud_cover_max": {"type": "number"},
                },
                "required": ["location"],
            },
        },
    }
]

response = client.chat.completions.create(
    model="gpt-4o",
    messages=[
        {"role": "user", "content": "Find satellite imagery of Tokyo with under 10% clouds."}
    ],
    tools=tools,
)

# The model will return a tool_call; you then execute it against the SkyFi API
# and feed the result back as a tool message.
print(json.dumps(response.choices[0].message.model_dump(), indent=2))
```

## First Search

Using the MCP bridge script:

```
You: Search for optical satellite imagery of Central Park, New York from the last 3 months.

  [calling geocode...]
  [calling search_archive...]

Assistant: I found 8 optical satellite images of Central Park from the last 3 months.
Here are the top results:
1. img-cp001 | Maxar | 0.5m resolution | 2026-02-28 | 5% cloud cover
2. img-cp002 | Airbus | 0.7m resolution | 2026-01-15 | 12% cloud cover
...
```

## Troubleshooting

| Issue | Fix |
|-------|-----|
| `openai.AuthenticationError` | Check your `OPENAI_API_KEY` |
| `SKYFI_API_KEY is not set` | Export the env var before running the bridge |
| Tool calls return empty results | Verify the SkyFi MCP server starts correctly with `uvx skyfi-mcp` |
| Rate limiting | Add retry logic or reduce request frequency |
