# Using SkyFi MCP with Vercel AI SDK

Integrate SkyFi satellite imagery tools with the Vercel AI SDK for TypeScript/JavaScript applications.

## Prerequisites

- Node.js 18+
- A deployed SkyFi MCP remote server, or the local server running
- Your SkyFi API key from [app.skyfi.com/settings/api](https://app.skyfi.com/settings/api)
- An LLM API key (OpenAI, Anthropic, or Google)

## Install Dependencies

```bash
npm install ai @ai-sdk/openai @modelcontextprotocol/sdk
```

For Anthropic or Google models:

```bash
npm install @ai-sdk/anthropic  # or @ai-sdk/google
```

## Setup

The Vercel AI SDK supports MCP through its experimental MCP client. You connect to the SkyFi MCP server, discover tools, and pass them to `generateText` or `streamText`.

### Using the Local Server (stdio)

```typescript
// skyfi-agent.ts
import { openai } from "@ai-sdk/openai";
import { generateText } from "ai";
import { experimental_createMCPClient as createMCPClient } from "ai";
import { Experimental_StdioMCPTransport as StdioTransport } from "ai";

async function main() {
  const mcpClient = await createMCPClient({
    transport: new StdioTransport({
      command: "uvx",
      args: ["skyfi-mcp"],
      env: {
        SKYFI_API_KEY: process.env.SKYFI_API_KEY!,
      },
    }),
  });

  const tools = await mcpClient.tools();

  const result = await generateText({
    model: openai("gpt-4o"),
    tools,
    maxSteps: 10,
    system:
      "You are a geospatial research assistant with access to SkyFi satellite " +
      "imagery tools. Help the user find, price, and order satellite imagery. " +
      "Never auto-confirm orders.",
    prompt:
      "Search for recent optical satellite imagery of the Panama Canal with less than 20% cloud cover.",
  });

  console.log(result.text);

  await mcpClient.close();
}

main();
```

### Using the Remote Server (Streamable HTTP)

```typescript
// skyfi-agent-remote.ts
import { anthropic } from "@ai-sdk/anthropic";
import { generateText } from "ai";
import { experimental_createMCPClient as createMCPClient } from "ai";

async function main() {
  const mcpClient = await createMCPClient({
    transport: {
      type: "sse",
      url: "https://skyfi-mcp.your-domain.workers.dev/sse",
      headers: {
        Authorization: `Bearer ${process.env.SKYFI_API_KEY}`,
      },
    },
  });

  const tools = await mcpClient.tools();

  const result = await generateText({
    model: anthropic("claude-sonnet-4-20250514"),
    tools,
    maxSteps: 10,
    prompt:
      "Compare pricing for 0.5m and 3.0m imagery of downtown Tokyo.",
  });

  console.log(result.text);
  await mcpClient.close();
}

main();
```

### Run

```bash
export SKYFI_API_KEY="your-skyfi-key"
export OPENAI_API_KEY="sk-..."  # or ANTHROPIC_API_KEY
npx tsx skyfi-agent.ts
```

## Streaming Responses

For streaming output (useful in web applications):

```typescript
import { openai } from "@ai-sdk/openai";
import { streamText } from "ai";
import { experimental_createMCPClient as createMCPClient } from "ai";
import { Experimental_StdioMCPTransport as StdioTransport } from "ai";

async function main() {
  const mcpClient = await createMCPClient({
    transport: new StdioTransport({
      command: "uvx",
      args: ["skyfi-mcp"],
      env: { SKYFI_API_KEY: process.env.SKYFI_API_KEY! },
    }),
  });

  const tools = await mcpClient.tools();

  const result = streamText({
    model: openai("gpt-4o"),
    tools,
    maxSteps: 10,
    prompt: "Find imagery of the Great Barrier Reef from this month.",
  });

  for await (const chunk of result.textStream) {
    process.stdout.write(chunk);
  }

  await mcpClient.close();
}

main();
```

## Next.js API Route Example

```typescript
// app/api/skyfi/route.ts
import { openai } from "@ai-sdk/openai";
import { streamText } from "ai";
import { experimental_createMCPClient as createMCPClient } from "ai";
import { Experimental_StdioMCPTransport as StdioTransport } from "ai";

export async function POST(req: Request) {
  const { prompt } = await req.json();

  const mcpClient = await createMCPClient({
    transport: new StdioTransport({
      command: "uvx",
      args: ["skyfi-mcp"],
      env: { SKYFI_API_KEY: process.env.SKYFI_API_KEY! },
    }),
  });

  const tools = await mcpClient.tools();

  const result = streamText({
    model: openai("gpt-4o"),
    tools,
    maxSteps: 10,
    system:
      "You are a satellite imagery assistant. Help users search and order imagery.",
    prompt,
  });

  return result.toDataStreamResponse();
}
```

## First Search

```
$ npx tsx skyfi-agent.ts

I found 6 optical satellite images of the Panama Canal with less than 20% cloud cover.
Here are the top results:
1. img-pan001 | Maxar | 0.3m | 2026-03-08 | 5% cloud
2. img-pan002 | Airbus | 0.5m | 2026-02-22 | 12% cloud
...
```

## Troubleshooting

| Issue | Fix |
|-------|-----|
| `Cannot find module 'ai'` | Run `npm install ai` |
| MCP client hangs | Ensure `uvx skyfi-mcp` works standalone |
| `SKYFI_API_KEY is not set` | Export the environment variable |
| TypeScript errors | Ensure `@types/node` is installed and `tsx` is available |
