export type ActionResult<T> =
  | { ok: true; value: T }
  | { ok: false; statusCode: 400 | 404 | 409; error: string };
