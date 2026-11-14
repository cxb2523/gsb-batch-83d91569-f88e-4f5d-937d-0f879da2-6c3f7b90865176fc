import { EXIT_CODES } from "./constants.js";

export class CliError extends Error {
  constructor(code, message, { exitCode = EXIT_CODES.EXECUTION, hint, details, cause } = {}) {
    super(message, cause ? { cause } : undefined);
    this.name = "CliError";
    this.code = code;
    this.exitCode = exitCode;
    this.hint = hint;
    this.details = details;
  }

  toJSON() {
    const error = { code: this.code, message: this.message };
    if (this.hint) error.hint = this.hint;
    if (this.details !== undefined) error.details = this.details;
    return error;
  }
}

const AUTH_CODES = new Set([
  "AUTH_REQUIRED",
  "AUTHENTICATION_REQUIRED",
  "LOGIN_REQUIRED",
  "NOT_AUTHENTICATED",
  "UNAUTHENTICATED",
  "SESSION_EXPIRED",
  "AUTH_SESSION_REQUIRED",
]);

const QUOTA_CODES = new Set([
  "QUOTA_EXCEEDED",
  "PUBLISH_QUOTA_EXCEEDED",
  "MONTHLY_QUOTA_EXCEEDED",
]);

const AUTHORIZATION_UNAVAILABLE_CODES = new Set([
  "AUTHORIZATION_UNAVAILABLE",
  "AUTHORIZATION_SERVICE_UNAVAILABLE",
  "AUTH_SERVICE_UNAVAILABLE",
  "AUTHORIZATION_FAILED_CLOSED",
  "PUBLISH_AUTHORIZATION_UNAVAILABLE",
]);

const BRIDGE_CODES = new Set([
  "BRIDGE_AMBIGUOUS",
  "BRIDGE_IDENTITY_MISMATCH",
  "BRIDGE_IDENTITY_UNAVAILABLE",
  "BRIDGE_IDENTITY_REQUIRED",
  "BRIDGE_UNAVAILABLE",
  "BRIDGE_TIMEOUT",
  "BRIDGE_CLOSED",
  "BRIDGE_PROTOCOL_ERROR",
  "EXTENSION_UNAVAILABLE",
  "HOST_UNAVAILABLE",
  "NATIVE_HOST_UNAVAILABLE",
  "NATIVE_MESSAGE_TOO_LARGE",
]);

const INPUT_CODES = new Set([
  "INVALID_INPUT",
  "INVALID_REQUEST",
  "INPUT_TOO_LARGE",
  "UNSUPPORTED_PROTOCOL",
  "INVALID_TASK",
  "INVALID_REQUEST_ID",
  "UNSUPPORTED_CONTENT_TYPE",
  "UNSUPPORTED_MODE",
  "INVALID_PLATFORMS",
  "UNSUPPORTED_PLATFORM",
  "INVALID_DATA",
  "INVALID_ASSETS",
  "INVALID_ASSET",
  "INVALID_ASSET_URL",
  "INVALID_SOURCE_URL",
  "INVALID_PAYLOAD_DIGEST",
  "DIGEST_MISMATCH",
  "REQUEST_TOO_LARGE",
]);

const CONFIRMATION_CODES = new Set([
  "CONFIRMATION_REQUIRED",
  "PUBLISH_CONFIRMATION_REQUIRED",
]);

export function exitCodeForRemoteCode(code) {
  const normalized = String(code || "").toUpperCase();
  if (AUTH_CODES.has(normalized)) return EXIT_CODES.AUTH;
  if (QUOTA_CODES.has(normalized)) return EXIT_CODES.QUOTA;
  if (AUTHORIZATION_UNAVAILABLE_CODES.has(normalized)) {
    return EXIT_CODES.AUTHORIZATION_UNAVAILABLE;
  }
  if (CONFIRMATION_CODES.has(normalized)) return EXIT_CODES.CONFIRMATION_REQUIRED;
  if (BRIDGE_CODES.has(normalized)) return EXIT_CODES.BRIDGE;
  if (INPUT_CODES.has(normalized)) return EXIT_CODES.INPUT;
  return EXIT_CODES.EXECUTION;
}

export function remoteErrorToCliError(error) {
  const value = error && typeof error === "object" ? error : {};
  const code = typeof value.code === "string" && value.code ? value.code : "EXECUTION_FAILED";
  const message =
    typeof value.message === "string" && value.message
      ? value.message
      : "一键发扩展未能完成请求";
  return new CliError(code, message, {
    exitCode: exitCodeForRemoteCode(code),
    hint: typeof value.hint === "string" ? value.hint : undefined,
    details: value.details,
  });
}

export function asCliError(error) {
  if (error instanceof CliError) return error;
  return new CliError("EXECUTION_FAILED", error?.message || "执行失败", {
    exitCode: EXIT_CODES.EXECUTION,
  });
}
