import { storeChatCompletionHistory } from "@openuidev/server/openai";
import OpenAI from "openai";
import type {
  ChatCompletionChunk,
  ChatCompletionMessageParam,
} from "openai/resources/chat/completions";
import { z } from "zod/v4";
import { f1PromptContext } from "../../../lib/f1/context";
import { f1Executors, f1FunctionTools } from "../../../lib/f1/tools";
import { frontendToken } from "../../../lib/frontend-token";
import { HistoryLoadError, loadChatCompletionHistory } from "../../../lib/gateway-history";
import { analyticsPrompt } from "../../../lib/prompt";
import { runChatToolLoop } from "../../../lib/tool-loop";
import { hasAllowedOrigin } from "../../../lib/same-origin";
import { readUserId } from "../../../lib/user-id";

export const runtime = "nodejs";

// Agent Interface's storage creates the Gateway conversation first and sends its id as threadId.
// The browser sends the whole thread; only its last message, the new question, is used.
const chatRequestSchema = z.object({
  // A Gateway conversation id, as Agent Interface's storage created it.
  threadId: z.string().max(256).regex(/^[A-Za-z0-9][A-Za-z0-9_-]*$/),
  messages: z
    .array(z.unknown())
    .min(1)
    .transform((messages) => messages.at(-1))
    .pipe(z.object({ role: z.literal("user"), content: z.string().trim().min(1).max(600) })),
});

// The thread's earlier turns, loaded from its Gateway conversation with their tool calls and
// results rather than taken from the browser, so every value the model sees came from a query
// this server ran. To send less of a long thread, compact the messages here.
function conversation(token: string, threadId: string, signal: AbortSignal) {
  return loadChatCompletionHistory({ frontendToken: token, conversationId: threadId, signal });
}

async function parseChatRequest(request: Request) {
  if (request.headers.get("content-type")?.split(";")[0].trim() !== "application/json")
    throw new Error("Send JSON.");
  const reader = request.body?.getReader();
  if (!reader) throw new Error("Send a question.");
  const chunks: Uint8Array[] = [];
  let size = 0;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      size += value.byteLength;
      if (size > 1_000_000) {
        await reader.cancel();
        throw new Error("Request too large.");
      }
      chunks.push(value);
    }
  } finally {
    reader.releaseLock();
  }
  return chatRequestSchema.parse(JSON.parse(Buffer.concat(chunks).toString("utf8")));
}

export async function POST(request: Request) {
  // No sign-in: requests come only from this app's pages, from an anonymous visitor (lib/user-id.ts).
  if (!hasAllowedOrigin(request))
    return Response.json(
      { error: "This example only accepts requests from its local chat interface." },
      { status: 403 },
    );
  let body;
  try {
    body = await parseChatRequest(request);
  } catch {
    return Response.json(
      { error: "Send a threadId and the thread's messages, ending with a question of up to 600 characters." },
      { status: 400 },
    );
  }
  const { threadId, messages: question } = body; // messages is narrowed to the last one
  const userId = readUserId(request);
  if (!userId) return Response.json({ error: "Missing visitor id." }, { status: 401 });
  const apiKey = process.env.THESYS_API_KEY;
  if (!apiKey)
    return Response.json(
      {
        error:
          "Configure THESYS_API_KEY privately in .env.local and restart to use OpenUI Gateway.",
      },
      { status: 503 },
    );

  const gateway = new OpenAI({ apiKey, baseURL: "https://api.thesys.dev/v1/embed" });
  // App-owned function tools, sent as the request's `tools` because the Gateway system prompt
  // carries no tool definitions. The loop runs only the names registered here.
  const tools = f1FunctionTools();
  const functionTools = f1Executors();
  // Read the thread as the visitor, not with the API key: Gateway refuses a thread that isn't
  // theirs, so knowing a conversation id isn't enough to read or add to someone else's chat.
  // Once it's confirmed theirs, the turn is stored with the key below.
  let history: ChatCompletionMessageParam[];
  try {
    const { token } = await frontendToken(apiKey, userId, request.signal);
    history = await conversation(token, threadId, request.signal);
  } catch (error) {
    if (error instanceof HistoryLoadError && (error.status === 403 || error.status === 404))
      return Response.json({ error: "This thread isn't available." }, { status: 404 });
    return Response.json({ error: "Could not load this thread from OpenUI Gateway." }, { status: 502 });
  }
  const context = await f1PromptContext(request.signal);
  const params = {
    model: process.env.OPENUI_MODEL || "openai/gpt-5.5",
    messages: [
      {
        role: "system" as const,
        content: analyticsPrompt({ today: new Date().toISOString().slice(0, 10), ...context }),
      },
      ...history,
      question,
    ],
    tools,
    max_completion_tokens: 6000,
  };

  // Open the first round before responding, so a rejected key, rate limit, or unknown model
  // returns as an HTTP error with Gateway's status instead of an event mid-stream.
  let firstStream: AsyncIterable<ChatCompletionChunk>;
  try {
    firstStream = await gateway.chat.completions.create(
      { ...params, stream: true },
      { signal: request.signal },
    );
  } catch (error) {
    const upstream = error as { status?: number; message?: string };
    return Response.json(
      { error: upstream.message ?? "OpenUI Gateway request failed." },
      { status: upstream.status ?? 502 },
    );
  }

  // Chat Completions doesn't write to the conversation, so store this turn when the run ends: the
  // user's message, then each message the run adds, which are the tool calls, their results, and
  // the answer. A stopped or failed run still stores the question and whatever finished before.
  const turn: ChatCompletionMessageParam[] = [question];

  // Stream AG-UI events to the browser, running app-owned tools between model turns.
  const encoder = new TextEncoder();
  let open = true;
  const stream = new ReadableStream<Uint8Array>({
    async start(controller) {
      // Stop sending once the browser disconnects.
      const emit = (event: Record<string, unknown>) => {
        if (open) controller.enqueue(encoder.encode(`data: ${JSON.stringify(event)}\n\n`));
      };
      try {
        await runChatToolLoop({
          client: gateway,
          params,
          firstStream,
          tools: functionTools,
          emit,
          signal: request.signal,
          maxRounds: 5,
          onMessage: (message) => turn.push(message),
        });
      } catch (error) {
        emit({
          type: "RUN_ERROR",
          message: error instanceof Error ? error.message : String(error),
        });
      } finally {
        // The stream ends once the turn is stored, so a follow-up question loads it.
        await storeChatCompletionHistory({ apiKey, conversationId: threadId, messages: turn }).catch(
          (error: unknown) => console.error("Could not store the turn in the Gateway conversation.", error),
        );
        if (open) controller.close();
      }
    },
    cancel() {
      open = false;
    },
  });

  return new Response(stream, {
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache, no-transform",
      Connection: "keep-alive",
    },
  });
}
