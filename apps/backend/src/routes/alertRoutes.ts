import { runWrite } from "../database/writeQueue";
import { takeReleaseAlerts } from "../releaseAlerts/releaseAlerts";
import type { BackendRouteContext } from "./context";

// The desktop app's notifications. POST because taking alerts marks them shown.
export function registerAlertRoutes({ app, db }: BackendRouteContext, { today }: { today: () => Date }) {
  app.post("/api/alerts/take", async () => ({ items: await runWrite(db, () => takeReleaseAlerts(db, today())) }));
}
