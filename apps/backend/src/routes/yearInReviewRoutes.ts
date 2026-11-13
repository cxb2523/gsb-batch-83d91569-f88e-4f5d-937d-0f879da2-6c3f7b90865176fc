import { createYearInReviewActions } from "../actions/yearInReviewActions";
import { sendActionResult } from "./actionResult";
import type { BackendRouteContext } from "./context";

export function registerYearInReviewRoutes({ app, db }: BackendRouteContext, { today }: { today: () => Date }) {
  const yearInReview = createYearInReviewActions(db, { today });

  app.get("/api/year-in-review/years", async () => yearInReview.years());

  app.get("/api/year-in-review/:year", async (request, reply) =>
    sendActionResult(reply, yearInReview.summary((request.params as { year: string }).year)));

  app.put("/api/year-in-review/:year/settings", async (request, reply) =>
    sendActionResult(reply, await yearInReview.saveSettings((request.params as { year: string }).year, request.body)));
}
