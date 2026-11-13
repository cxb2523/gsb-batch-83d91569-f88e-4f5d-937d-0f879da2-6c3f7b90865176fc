import { describe, expect, test } from "vitest";
import { backendChildEnv } from "../../apps/desktop/src/backendProcess";

const parent = { PATH: "/bin", IGDB_CLIENT_ID: "from-shell", IGDB_CLIENT_SECRET: "s", IGDB_ACCESS_TOKEN: "t", STEAMGRIDDB_API_KEY: "k" };
const extras = { GRT_DATA_DIR: "/data", GRT_API_TOKEN: "token" };

describe("backend child environment", () => {
  test("the packaged app uses only the API keys saved in Settings, never ones from the environment", () => {
    expect(backendChildEnv(parent, extras, { packaged: true })).toEqual({ PATH: "/bin", GRT_DATA_DIR: "/data", GRT_API_TOKEN: "token" });
  });

  test("development keeps the environment's keys as a fallback", () => {
    expect(backendChildEnv(parent, extras, { packaged: false })).toEqual({ ...parent, ...extras });
  });
});
