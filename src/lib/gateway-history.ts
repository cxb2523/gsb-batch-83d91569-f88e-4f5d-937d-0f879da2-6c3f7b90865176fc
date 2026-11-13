import type {
  ChatCompletionMessageFunctionToolCall,
  ChatCompletionMessageParam,
} from "openai/resources/chat/completions";
import { FRONTEND_TOKEN_HEADER } from "./frontend-token";

// A conversation item, in the shape storeChatCompletionHistory() stores it.
type ConversationItem = {
  type: string;
  role?: string;
  content?: { text?: string }[];
  call_id?: string;
  name?: string;
  arguments?: string;
  output?: string;
};

/** Gateway refused or failed a history read; `status` says which (403/404: not this visitor's). */
export class HistoryLoadError extends Error {
  constructor(readonly status: number) {
    super(`Could not load the thread from Gateway: ${status}`);
  }
}

// Loads a thread's stored turns from its Gateway conversation as Chat Completions messages, the
// reverse of storeChatCompletionHistory(): questions, answers, tool calls, and tool results.
// It reads with the visitor's frontend token, so Gateway only returns the visitor's own thread.
export async function loadChatCompletionHistory(options: {
  frontendToken: string;
  conversationId: string;
  signal?: AbortSignal;
}): Promise<ChatCompletionMessageParam[]> {
  const items: ConversationItem[] = [];
  let after: string | undefined;
  do {
    const query = new URLSearchParams({ order: "asc", limit: "100" });
    if (after) query.set("after", after);
    const response = await fetch(
      `https://api.thesys.dev/v1/conversations/${encodeURIComponent(options.conversationId)}/items?${query}`,
      { headers: { [FRONTEND_TOKEN_HEADER]: options.frontendToken }, signal: options.signal },
    );
    if (!response.ok) throw new HistoryLoadError(response.status);
    const page = (await response.json()) as {
      data: ConversationItem[];
      has_more: boolean;
      last_id: string;
    };
    items.push(...page.data);
    after = page.has_more ? page.last_id : undefined;
  } while (after);
  return toChatMessages(items);
}

function toChatMessages(items: ConversationItem[]) {
  // Chat Completions rejects a tool call without a result, so drop the calls of a stopped run.
  const answered = new Set(
    items.flatMap((item) => (item.type === "function_call_output" ? [item.call_id] : [])),
  );
  const messages: ChatCompletionMessageParam[] = [];
  for (const item of items) {
    if (item.type === "message" && (item.role === "user" || item.role === "assistant")) {
      const text = (item.content ?? []).map((part) => part.text ?? "").join("");
      if (text) messages.push({ role: item.role, content: text });
    } else if (item.type === "function_call" && item.call_id && answered.has(item.call_id)) {
      const call: ChatCompletionMessageFunctionToolCall = {
        id: item.call_id,
        type: "function",
        function: { name: item.name ?? "", arguments: item.arguments ?? "{}" },
      };
      // A completion's text and its tool calls make up one assistant message.
      const last = messages.at(-1);
      if (last?.role === "assistant") (last.tool_calls ??= []).push(call);
      else messages.push({ role: "assistant", content: null, tool_calls: [call] });
    } else if (item.type === "function_call_output" && item.call_id) {
      messages.push({ role: "tool", tool_call_id: item.call_id, content: item.output ?? "" });
    }
  }
  return messages;
}
