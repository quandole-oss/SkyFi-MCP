# Using SkyFi MCP with Google Gemini

Integrate SkyFi satellite imagery tools with Google's Gemini models.

## Prerequisites

- Google Cloud project with the Gemini API enabled, or a Gemini API key from [aistudio.google.com](https://aistudio.google.com)
- Python 3.11+ with [uv](https://docs.astral.sh/uv/) installed
- Your SkyFi API key from [app.skyfi.com/settings/api](https://app.skyfi.com/settings/api)

## Approach

Gemini supports function calling. The integration uses the `mcp` Python SDK to connect to the SkyFi MCP server as a client, discovers available tools, and translates them into Gemini function declarations.

## Install Dependencies

```bash
pip install google-genai mcp
```

## Bridge Script

```python
"""Bridge: SkyFi MCP tools -> Gemini function calling."""

import asyncio
import json
import os

from google import genai
from google.genai import types
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
SKYFI_API_KEY = os.environ["SKYFI_API_KEY"]


def mcp_tool_to_gemini_declaration(tool) -> dict:
    """Convert an MCP tool definition to a Gemini function declaration."""
    # Gemini expects a specific format for function declarations
    schema = tool.inputSchema.copy() if tool.inputSchema else {"type": "object", "properties": {}}
    # Remove $schema and other JSON Schema keys Gemini does not support
    schema.pop("$schema", None)
    schema.pop("additionalProperties", None)

    return {
        "name": tool.name,
        "description": tool.description or "",
        "parameters": schema,
    }


async def main():
    gemini_client = genai.Client(api_key=GEMINI_API_KEY)

    server_params = StdioServerParameters(
        command="uvx",
        args=["skyfi-mcp"],
        env={"SKYFI_API_KEY": SKYFI_API_KEY},
    )

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # Discover tools
            tools_result = await session.list_tools()
            gemini_tools = types.Tool(
                function_declarations=[
                    mcp_tool_to_gemini_declaration(t) for t in tools_result.tools
                ]
            )

            print("SkyFi + Gemini Bridge (type 'quit' to exit)")
            print("-" * 50)

            chat = gemini_client.chats.create(
                model="gemini-2.0-flash",
                config=types.GenerateContentConfig(
                    system_instruction=(
                        "You are a geospatial research assistant with access to "
                        "SkyFi satellite imagery tools. Help the user find, price, "
                        "and order satellite imagery. Never auto-confirm orders."
                    ),
                    tools=[gemini_tools],
                ),
            )

            while True:
                user_input = input("\nYou: ").strip()
                if user_input.lower() in ("quit", "exit"):
                    break

                response = chat.send_message(user_input)

                # Handle function calls
                while response.candidates[0].content.parts:
                    function_calls = [
                        p for p in response.candidates[0].content.parts
                        if p.function_call
                    ]
                    if not function_calls:
                        break

                    function_responses = []
                    for part in function_calls:
                        fc = part.function_call
                        args = dict(fc.args) if fc.args else {}
                        print(f"  [calling {fc.name}...]")

                        result = await session.call_tool(fc.name, arguments=args)
                        tool_content = (
                            result.content[0].text if result.content else "{}"
                        )

                        function_responses.append(
                            types.Part.from_function_response(
                                name=fc.name,
                                response=json.loads(tool_content),
                            )
                        )

                    response = chat.send_message(function_responses)

                # Print text response
                text_parts = [
                    p.text for p in response.candidates[0].content.parts
                    if hasattr(p, "text") and p.text
                ]
                if text_parts:
                    print(f"\nAssistant: {''.join(text_parts)}")


if __name__ == "__main__":
    asyncio.run(main())
```

## Run

```bash
export GEMINI_API_KEY="your-gemini-key"
export SKYFI_API_KEY="your-skyfi-key"
python gemini_skyfi_bridge.py
```

## First Search

```
You: Find SAR satellite imagery of the Strait of Hormuz from this year.

  [calling geocode...]
  [calling search_archive...]

Assistant: I found 5 SAR imagery results covering the Strait of Hormuz.
SAR imagery is ideal for this area as it can capture through clouds.
1. img-soh001 | Capella Space | 0.5m | 2026-01-20 | SAR
2. img-soh002 | ICEYE | 1.0m | 2026-02-14 | SAR
...
```

## Using with Vertex AI

For production deployments on Google Cloud, replace the API key client with Vertex AI:

```python
from google import genai

client = genai.Client(
    vertexai=True,
    project="your-gcp-project",
    location="us-central1",
)
```

The rest of the bridge script remains the same.

## Troubleshooting

| Issue | Fix |
|-------|-----|
| `google.auth.exceptions.DefaultCredentialsError` | Set `GEMINI_API_KEY` or configure Application Default Credentials |
| Function call arguments are empty | Gemini sometimes needs more specific prompts; add detail to your query |
| `SKYFI_API_KEY is not set` | Export the env var before running |
| Timeout on tool calls | The MCP server process may have crashed; check stderr output |
