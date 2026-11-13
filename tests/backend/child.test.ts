import { describe, expect, test, vi } from "vitest";
import { getBackendChildPath, getBackendCwd, parseReadyMessage, stopBackendProcess } from "../../apps/desktop/src/backendProcess";

describe("backend ready handshake", () => {
  test("extracts dynamic port from child ready JSON", () => {
    expect(parseReadyMessage('{"type":"ready","port":49870}')).toEqual({ type: "ready", port: 49870 });
    expect(parseReadyMessage("not json")).toBeNull();
  });

  test("keeps backend script in app.asar but uses physical resources cwd", () => {
    if (process.platform === "win32") {
      expect(getBackendChildPath("C:\\app\\resources\\app.asar")).toBe("C:\\app\\resources\\app.asar\\dist\\apps\\backend\\src\\child.js");
      expect(getBackendCwd("C:\\app\\resources\\app.asar")).toBe("C:\\app\\resources");
    } else {
      expect(getBackendChildPath("/app/resources/app.asar")).toBe("/app/resources/app.asar/dist/apps/backend/src/child.js");
      expect(getBackendCwd("/app/resources/app.asar")).toBe("/app/resources");
    }
  });

  test("asks backend to shut down and waits for exit before killing", async () => {
    const listeners = new Map<string, (value?: unknown) => void>();
    const child = {
      killed: false,
      postMessage: vi.fn(),
      send: vi.fn(),
      kill: vi.fn(),
      once: vi.fn((event: string, listener: (value?: unknown) => void) => {
        listeners.set(event, listener);
      })
    };

    const stopped = stopBackendProcess(child, 200);
    listeners.get("exit")?.(0);

    await expect(stopped).resolves.toBe(true);
    expect(child.postMessage).toHaveBeenCalledWith({ type: "shutdown" });
    expect(child.send).toHaveBeenCalledWith({ type: "shutdown" });
    expect(child.kill).not.toHaveBeenCalled();
  });
});
