import type { ActionResult } from "../actions/actionResult";

// The one reply method a failed action needs; a Fastify reply satisfies it.
interface ErrorReply {
  code(statusCode: number): { send(payload: unknown): unknown };
}

export function sendActionResult<T>(reply: ErrorReply, result: ActionResult<T>) {
  if (!result.ok) return reply.code(result.statusCode).send({ error: result.error });
  return result.value;
}
