import { EventEmitter } from "node:events";
import { describe, expect, test, vi } from "vitest";
import { waitForBackendReady } from "../../apps/desktop/src/backendProcess";
import { handleStartupFailure } from "../../apps/desktop/src/desktopLifecycle";

function fakeChild() {
  const child = new EventEmitter() as EventEmitter & { killed: boolean; kill: () => boolean; stdout: EventEmitter; stderr: EventEmitter };
  child.killed = false;
  child.kill = vi.fn(() => { child.killed = true; return true; });
  child.stdout = new EventEmitter();
  child.stderr = new EventEmitter();
  return child;
}

describe("backend startup", () => {
  test("resolves with the port once the backend reports ready", async () => {
    const child = fakeChild();
    const ready = waitForBackendReady(child, { timeoutMs: 1000 });

    child.emit("message", { type: "ready", port: 4312 });

    await expect(ready).resolves.toEqual({ child, port: 4312 });
    expect(child.kill).not.toHaveBeenCalled();
  });

  test("a backend that fails at startup reports its own reason, not just an exit code", async () => {
    const child = fakeChild();
    const ready = waitForBackendReady(child, { timeoutMs: 1000 });

    child.stdout.emit("data", `${JSON.stringify({ type: "error", message: "This library was saved by a newer version of Game Release Tracker" })}\n`);
    child.emit("exit", 1);

    await expect(ready).rejects.toThrow("This library was saved by a newer version of Game Release Tracker");
  });

  test("the startup reason is read from stderr, where the backend prints it", async () => {
    const child = fakeChild();
    const ready = waitForBackendReady(child, { timeoutMs: 1000 });

    child.stderr.emit("data", `${JSON.stringify({ type: "error", message: "This library was saved by a newer version of Game Release Tracker" })}\n`);
    child.emit("exit", 1);

    await expect(ready).rejects.toThrow("This library was saved by a newer version of Game Release Tracker");
  });

  test("the startup reason can arrive as a process message", async () => {
    const child = fakeChild();
    const ready = waitForBackendReady(child, { timeoutMs: 1000 });

    child.emit("message", { type: "error", message: "Database is locked" });
    child.emit("exit", 1);

    await expect(ready).rejects.toThrow("Database is locked");
  });

  test("a backend that never becomes ready is stopped, not left running", async () => {
    const child = fakeChild();

    await expect(waitForBackendReady(child, { timeoutMs: 20 })).rejects.toThrow("Backend startup timed out");

    expect(child.kill).toHaveBeenCalledTimes(1);
  });
});

describe("startup failure", () => {
  test("logs, tells the user, stops the backend and quits", async () => {
    const steps: string[] = [];

    await handleStartupFailure(new Error("port in use"), {
      logFatal: error => { steps.push(`log:${(error as Error).message}`); return "port in use"; },
      showError: message => steps.push(`dialog:${message}`),
      stopBackend: async () => { steps.push("stop"); },
      quit: () => steps.push("quit")
    });

    expect(steps).toEqual(["log:port in use", "dialog:port in use", "stop", "quit"]);
  });

  test("still quits when stopping the backend fails", async () => {
    const quit = vi.fn();

    await handleStartupFailure(new Error("boom"), {
      logFatal: () => "boom",
      showError: () => undefined,
      stopBackend: async () => { throw new Error("already gone"); },
      quit
    });

    expect(quit).toHaveBeenCalledTimes(1);
  });
});
