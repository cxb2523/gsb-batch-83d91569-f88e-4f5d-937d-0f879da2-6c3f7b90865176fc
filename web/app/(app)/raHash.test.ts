import { zipSync } from "fflate";
import { md5 } from "js-md5";
import { describe, expect, it } from "vitest";
import { computeRaHash } from "./raHash";

const EMPTY_MD5 = "D41D8CD98F00B204E9800998ECF8427E";

describe("computeRaHash", () => {
  it("strips the 512-byte header on a headered PC Engine ROM (size & 512, not size % 131072)", () => {
    // 131072 (128KB, tamaño típico sin header) + 512 de header = 131584.
    // La regla correcta es "size & 512" (bit test); la vieja regla rota de
    // src/core/source_resync.py::_ra_hash era "size % 131072 === 0", que en
    // 131584 da 512 (!= 0) y NO recortaría el header -- si raHash.ts
    // regresara a esa regla, este test fallaría.
    const bytes = new Uint8Array(131584).fill(0xab);
    const result = computeRaHash("game.pce", bytes);
    expect("error" in result).toBe(false);
    expect((result as { hash: string }).hash).toBe(md5(bytes.slice(512)).toUpperCase());
  });

  it("does not touch a headerless PC Engine ROM (131072 bytes, no header bit set)", () => {
    // Con la regla rota "size % 131072 === 0", 131072 % 131072 === 0 es
    // verdadero -> recortaría 512 bytes de un ROM que no tiene header.
    const bytes = new Uint8Array(131072).fill(0xab);
    const result = computeRaHash("game.pce", bytes);
    expect("error" in result).toBe(false);
    expect((result as { hash: string }).hash).toBe(md5(bytes).toUpperCase());
  });

  it("strips the 16-byte iNES header on NES ROMs by signature", () => {
    const header = new Uint8Array([0x4e, 0x45, 0x53, 0x1a, ...new Array(12).fill(0)]);
    const bytes = new Uint8Array([...header]);
    const result = computeRaHash("game.nes", bytes);
    expect("error" in result).toBe(false);
    expect((result as { hash: string }).hash).toBe(EMPTY_MD5);
  });

  it("hashes simple extensions (no header rule) as-is", () => {
    const bytes = new Uint8Array([1, 2, 3, 4]);
    const result = computeRaHash("game.gb", bytes);
    expect("error" in result).toBe(false);
    expect((result as { consoleGuess: string }).consoleGuess).toBe("Game Boy");
  });

  it("returns an error for an unrecognized extension", () => {
    const result = computeRaHash("game.unknownext", new Uint8Array([1]));
    expect("error" in result).toBe(true);
  });

  it("unzips a .zip and hashes its largest entry", () => {
    const rom = new Uint8Array([1, 2, 3, 4]);
    const zipped = zipSync({
      "readme.txt": new Uint8Array([0]),
      "game.gb": rom,
    });

    const result = computeRaHash("game.zip", zipped);

    expect("error" in result).toBe(false);
    expect((result as { hash: string }).hash).toBe(md5(rom).toUpperCase());
    expect((result as { consoleGuess: string }).consoleGuess).toBe("Game Boy");
  });

  it("returns an error for a corrupt .zip", () => {
    const result = computeRaHash("game.zip", new Uint8Array([1, 2, 3]));
    expect(result).toEqual({ error: "El archivo .zip está dañado o no se pudo leer." });
  });
});
