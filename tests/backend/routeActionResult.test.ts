import { describe, expect, test } from "vitest";
import { sendActionResult } from "../../apps/backend/src/routes/actionResult";

describe("route action result adapter", () => {
  test("returns successful action values without touching reply status", () => {
    const reply = fakeReply();

    expect(sendActionResult(reply, { ok: true, value: { ok: true, item: "release" } })).toEqual({ ok: true, item: "release" });
    expect(reply.statusCode).toBeUndefined();
    expect(reply.sent).toBeUndefined();
  });

  test("turns failed action results into route errors", () => {
    const reply = fakeReply();

    expect(sendActionResult(reply, { ok: false, statusCode: 404, error: "Release not found" })).toEqual({ error: "Release not found" });
    expect(reply.statusCode).toBe(404);
    expect(reply.sent).toEqual({ error: "Release not found" });
  });
});

function fakeReply() {
  return {
    statusCode: undefined as number | undefined,
    sent: undefined as unknown,
    code(statusCode: number) {
      this.statusCode = statusCode;
      return this;
    },
    send(payload: unknown) {
      this.sent = payload;
      return payload;
    }
  };
}
