import os from "node:os";
import { MAX_NATIVE_MESSAGE_BYTES } from "./constants.js";

export class NativeFramingError extends Error {
  constructor(code, message) {
    super(message);
    this.name = "NativeFramingError";
    this.code = code;
  }
}

const littleEndian = os.endianness() === "LE";

function readNativeUInt32(buffer, offset = 0) {
  return littleEndian ? buffer.readUInt32LE(offset) : buffer.readUInt32BE(offset);
}

function writeNativeUInt32(buffer, value, offset = 0) {
  if (littleEndian) buffer.writeUInt32LE(value, offset);
  else buffer.writeUInt32BE(value, offset);
}

export class NativeMessageParser {
  constructor({ maxBytes = MAX_NATIVE_MESSAGE_BYTES } = {}) {
    this.maxBytes = maxBytes;
    this.buffer = Buffer.alloc(0);
    this.expectedBytes = null;
  }

  push(chunk) {
    if (!Buffer.isBuffer(chunk)) chunk = Buffer.from(chunk);
    this.buffer = this.buffer.length ? Buffer.concat([this.buffer, chunk]) : chunk;
    const messages = [];
    while (true) {
      if (this.expectedBytes === null) {
        if (this.buffer.length < 4) break;
        this.expectedBytes = readNativeUInt32(this.buffer);
        this.buffer = this.buffer.subarray(4);
        if (this.expectedBytes > this.maxBytes) {
          throw new NativeFramingError(
            "NATIVE_MESSAGE_TOO_LARGE",
            `Native message is ${this.expectedBytes} bytes; maximum is ${this.maxBytes}`,
          );
        }
      }
      if (this.buffer.length < this.expectedBytes) break;
      const body = this.buffer.subarray(0, this.expectedBytes);
      this.buffer = this.buffer.subarray(this.expectedBytes);
      this.expectedBytes = null;
      try {
        messages.push(JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(body)));
      } catch (error) {
        throw new NativeFramingError("INVALID_NATIVE_JSON", `Invalid native message JSON: ${error.message}`);
      }
    }
    return messages;
  }

  finish() {
    if (this.expectedBytes !== null || this.buffer.length) {
      throw new NativeFramingError("TRUNCATED_NATIVE_MESSAGE", "Native message stream ended mid-frame");
    }
  }
}

export function encodeNativeMessage(value, { maxBytes = MAX_NATIVE_MESSAGE_BYTES } = {}) {
  const body = Buffer.from(JSON.stringify(value), "utf8");
  if (body.length > maxBytes) {
    throw new NativeFramingError(
      "NATIVE_MESSAGE_TOO_LARGE",
      `Native message is ${body.length} bytes; maximum is ${maxBytes}`,
    );
  }
  const header = Buffer.allocUnsafe(4);
  writeNativeUInt32(header, body.length);
  return Buffer.concat([header, body]);
}

export async function writeNativeMessage(stream, value, options) {
  const frame = encodeNativeMessage(value, options);
  if (stream.write(frame)) return;
  await new Promise((resolve, reject) => {
    stream.once("drain", resolve);
    stream.once("error", reject);
  });
}
