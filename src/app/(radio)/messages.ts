import { parseMessage } from "@openuidev/lang-core";
import type { AssistantMessage, Message } from "@openuidev/react-headless";

/*
 * Message helpers for the Radio chat. Messages can carry OpenUI's content/context envelope (a
 * follow-up click sends its label as content and the form state as context); lang-core's
 * parseMessage() and buildMessage() read and write it. A turn is a user message followed by every
 * assistant and tool message until the next one.
 */

/** Plain text of a message's content, envelope removed. */
export function messageText(content: Message["content"]): string {
  if (typeof content === "string") return parseMessage(content).content;
  if (Array.isArray(content))
    return content
      .map((part) => (part && typeof part === "object" && "text" in part ? String(part.text) : ""))
      .join(" ");
  return "";
}

/** Whether an answer has started writing OpenUI Lang (a fence or a root binding). */
export const hasLangSyntax = (content: string) =>
  !!content && (content.includes("```openui-lang") || /(^|\n)\s*root\s*=/.test(content));

export type Turn =
  | { kind: "user"; message: Message }
  | { kind: "assistant"; id: string; segments: AssistantMessage[] };

export function groupIntoTurns(messages: Message[]): Turn[] {
  const turns: Turn[] = [];
  let current: Extract<Turn, { kind: "assistant" }> | null = null;
  for (const message of messages) {
    if (message.role === "assistant" || message.role === "tool") {
      if (!current) {
        current = { kind: "assistant", id: message.id, segments: [] };
        turns.push(current);
      }
      if (message.role === "assistant") current.segments.push(message as AssistantMessage);
    } else {
      current = null;
      if (message.role === "user") turns.push({ kind: "user", message });
    }
  }
  return turns;
}
