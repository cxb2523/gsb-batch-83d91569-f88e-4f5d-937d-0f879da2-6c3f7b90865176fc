import { afterEach, describe, expect, test } from "vitest";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import type { SaveDialogOptions } from "electron";
import { pngBytes, registerSaveImageIpc, safeImageName, saveImage, type SaveImageIpcEvent } from "../../apps/desktop/src/saveImageIpc";

const dirs: string[] = [];
afterEach(() => {
  for (const dir of dirs) rmSync(dir, { recursive: true, force: true });
  dirs.length = 0;
});

function tempDir() {
  const dir = mkdtempSync(join(tmpdir(), "grt-save-image-"));
  dirs.push(dir);
  return dir;
}

const png = new Uint8Array([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 1, 2, 3]);

describe("save image", () => {
  test("takes only PNG bytes", () => {
    expect(pngBytes(png)).toEqual(Buffer.from(png));
    expect(pngBytes(new Uint8Array([1, 2, 3, 4, 5, 6, 7, 8, 9]))).toBeNull();
    expect(pngBytes("not bytes")).toBeNull();
    expect(pngBytes(null)).toBeNull();
  });

  test("file names keep to safe characters and always end in .png", () => {
    expect(safeImageName("Year in Review 2026 - Horizontal")).toBe("Year in Review 2026 - Horizontal.png");
    expect(safeImageName("..\\..\\evil/../x:?*")).toBe("evil x.png");
    expect(safeImageName("")).toBe("Year in Review.png");
  });

  test("saves the image where the user chose, as .png", async () => {
    const dir = tempDir();
    let offered: SaveDialogOptions = {};
    const result = await saveImage({
      dialog: { showSaveDialog: async options => { offered = options; return { canceled: false, filePath: join(dir, "mine") }; } },
      defaultDir: dir,
      data: png,
      suggestedName: "Year in Review 2026 - Vertical"
    });

    expect(offered.defaultPath).toBe(join(dir, "Year in Review 2026 - Vertical.png"));
    expect(result).toEqual({ ok: true, path: join(dir, "mine.png") });
    expect(readFileSync(join(dir, "mine.png"))).toEqual(Buffer.from(png));
  });

  test("a cancelled dialog or a non-PNG writes nothing", async () => {
    const dialog = { showSaveDialog: async () => ({ canceled: true }) };
    expect(await saveImage({ dialog, defaultDir: tempDir(), data: png, suggestedName: "x" })).toEqual({ ok: false, canceled: true });
    expect(await saveImage({ dialog, defaultDir: tempDir(), data: new Uint8Array([1]), suggestedName: "x" })).toEqual({ ok: false, error: "That isn't a PNG image" });
  });

  test("the IPC answers only the app's own frame", async () => {
    let handler!: (event: SaveImageIpcEvent, ...args: unknown[]) => unknown;
    const dir = tempDir();
    registerSaveImageIpc({
      ipcMain: { handle: (_channel, next) => { handler = next; } },
      dialog: { showSaveDialog: async () => ({ canceled: false, filePath: join(dir, "a.png") }) },
      getDefaultDir: () => dir,
      isAppFrame: url => url.startsWith("http://127.0.0.1:")
    });

    expect(await handler({ senderFrame: { url: "https://evil.example" } }, png, "x")).toEqual({ ok: false, error: "Refused" });
    expect(await handler({ senderFrame: { url: "http://127.0.0.1:4000/" } }, png, "x")).toEqual({ ok: true, path: join(dir, "a.png") });
  });
});
