import { describe, expect, test, vi } from "vitest";
import { deleteManyReleases, deleteOneRelease } from "../../apps/frontend/src/releaseDeletion";

function deletionDeps(confirmResult = true) {
  const events: Array<{ event: string; details: Record<string, unknown> }> = [];
  const deleted: Array<{ id: string; block: boolean }> = [];
  return {
    events,
    deleted,
    deps: {
      confirm: vi.fn(() => confirmResult),
      alert: vi.fn(),
      deleteRelease: vi.fn(async (id: string, block: boolean) => {
        deleted.push({ id, block });
      }),
      log: vi.fn((event: string, details: Record<string, unknown>) => {
        events.push({ event, details });
      })
    }
  };
}

describe("release deletion workflow", () => {
  test("single delete owns confirmation, transport, and diagnostics", async () => {
    const { deps, events, deleted } = deletionDeps();

    const result = await deleteOneRelease({ id: "manual-1", title: "Manual Game" }, "delete", deps);

    expect(result).toEqual({ status: "deleted", deletedIds: ["manual-1"] });
    expect(deps.confirm).toHaveBeenCalledWith('Delete "Manual Game"?');
    expect(deleted).toEqual([{ id: "manual-1", block: false }]);
    expect(events.map(event => event.event)).toEqual([
      "ui.click",
      "ui.confirm.accepted",
      "ui.delete.succeeded"
    ]);
    expect(events[0].details).toMatchObject({ action: "delete", id: "manual-1", title: "Manual Game" });
  });

  test("delete and block sends block=true and logs the block action vocabulary", async () => {
    const { deps, events, deleted } = deletionDeps();

    const result = await deleteOneRelease({ id: "igdb-1", title: "Blocked Game" }, "delete-block", deps);

    expect(result.status).toBe("deleted");
    expect(deps.confirm).toHaveBeenCalledWith('Delete "Blocked Game" and block it from future syncs?');
    expect(deleted).toEqual([{ id: "igdb-1", block: true }]);
    expect(events.map(event => event.details.action)).toEqual(["delete-block", "delete-block", "delete-block"]);
  });

  test("cancellation logs and does not call delete", async () => {
    const { deps, events, deleted } = deletionDeps(false);

    const result = await deleteOneRelease({ id: "manual-1", title: "Manual Game" }, "delete", deps);

    expect(result).toEqual({ status: "cancelled", deletedIds: [] });
    expect(deleted).toEqual([]);
    expect(events.map(event => event.event)).toEqual(["ui.click", "ui.confirm.cancelled"]);
  });

  test("a failed single delete alerts, logs the failure and reports nothing deleted", async () => {
    const { deps, events } = deletionDeps();
    deps.deleteRelease.mockImplementation(async () => {
      throw new Error("locked");
    });

    const result = await deleteOneRelease({ id: "manual-1", title: "Manual Game" }, "delete", deps);

    expect(result).toEqual({ status: "failed", deletedIds: [], error: "locked" });
    expect(deps.alert).toHaveBeenCalledWith("Delete failed: locked");
    expect(events.map(event => event.event)).toEqual(["ui.click", "ui.confirm.accepted", "ui.delete.failed"]);
  });

  test("bulk delete owns confirmation, per-release transport, and partial failure diagnostics", async () => {
    const { deps, events } = deletionDeps();
    deps.deleteRelease.mockImplementation(async (id: string, block: boolean) => {
      if (id === "metaphor") throw new Error("404 Not Found");
    });

    const result = await deleteManyReleases([
      { id: "p4", title: "Persona 4 Revival" },
      { id: "metaphor", title: "Metaphor Expansion" }
    ], "delete-block", deps);

    expect(result).toEqual({ status: "failed", deletedIds: ["p4"], error: "404 Not Found" });
    expect(deps.confirm).toHaveBeenCalledWith("Delete and block 2 selected releases?");
    expect(deps.deleteRelease).toHaveBeenNthCalledWith(1, "p4", true);
    expect(deps.deleteRelease).toHaveBeenNthCalledWith(2, "metaphor", true);
    expect(deps.alert).toHaveBeenCalledWith("Bulk delete failed: 404 Not Found");
    expect(events.map(event => event.event)).toEqual([
      "ui.click",
      "ui.confirm.accepted",
      "ui.bulk-delete.failed"
    ]);
    expect(events[2].details).toMatchObject({
      action: "bulk-delete-block",
      count: 2,
      ids: ["p4", "metaphor"],
      error: "404 Not Found"
    });
  });
});
