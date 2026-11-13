import { clearSettingsCredentials, readSettingsStatus, testSettingsCredentials, updateSettingsCredentials } from "../settings/settingsCredentialModule";
import type { BackendRouteContext } from "./context";

export function registerSettingsRoutes({ app, db, igdb }: BackendRouteContext) {
  app.get("/api/settings", async () => readSettingsStatus(db));

  app.patch("/api/settings", async request => {
    const payload = request.body as Record<string, string | undefined>;
    return updateSettingsCredentials(db, payload);
  });

  app.delete("/api/settings/credentials", async () => clearSettingsCredentials(db));

  app.post("/api/settings/test-credentials", async () => testSettingsCredentials(db, igdb));
}
