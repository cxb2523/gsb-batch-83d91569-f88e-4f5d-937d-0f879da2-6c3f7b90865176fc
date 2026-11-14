import { MAX_NATIVE_MESSAGE_BYTES } from "./constants.js";

export class NdjsonError extends Error {
  constructor(code, message) {
    super(message);
    this.name = "NdjsonError";
    this.code = code;
  }
}

export class NdjsonParser {
  constructor({ maxBytes = MAX_NATIVE_MESSAGE_BYTES } = {}) {
    this.maxBytes = maxBytes;
    this.buffer = Buffer.alloc(0);
  }

  push(chunk) {
    if (!Buffer.isBuffer(chunk)) chunk = Buffer.from(chunk);
    this.buffer = this.buffer.length ? Buffer.concat([this.buffer, chunk]) : chunk;
    if (this.buffer.length > this.maxBytes && !this.buffer.includes(0x0a)) {
      throw new NdjsonError("NDJSON_MESSAGE_TOO_LARGE", "NDJSON message exceeds size limit");
    }
    const messages = [];
    while (true) {
      const newline = this.buffer.indexOf(0x0a);
      if (newline < 0) break;
      let line = this.buffer.subarray(0, newline);
      this.buffer = this.buffer.subarray(newline + 1);
      if (line.length && line[line.length - 1] === 0x0d) line = line.subarray(0, -1);
      if (!line.length) continue;
      if (line.length > this.maxBytes) {
        throw new NdjsonError("NDJSON_MESSAGE_TOO_LARGE", "NDJSON message exceeds size limit");
      }
      try {
        messages.push(JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(line)));
      } catch (error) {
        throw new NdjsonError("INVALID_NDJSON", `Invalid NDJSON: ${error.message}`);
      }
    }
    return messages;
  }

  finish() {
    if (this.buffer.length === 0) return [];
    return this.push(Buffer.from("\n"));
  }
}

export function encodeNdjson(value, { maxBytes = MAX_NATIVE_MESSAGE_BYTES } = {}) {
  const body = Buffer.from(`${JSON.stringify(value)}\n`, "utf8");
  if (body.length - 1 > maxBytes) {
    throw new NdjsonError("NDJSON_MESSAGE_TOO_LARGE", "NDJSON message exceeds size limit");
  }
  return body;
}
