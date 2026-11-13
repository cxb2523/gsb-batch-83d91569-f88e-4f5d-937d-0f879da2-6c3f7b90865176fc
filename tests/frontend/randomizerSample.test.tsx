// @vitest-environment jsdom
import { act } from "react";
import { afterEach, describe, expect, test } from "vitest";
import { AppShell } from "../../apps/frontend/src/App";
import { fakeApiClient } from "./fakeApiClient";
import { click, getButton, renderInteractive } from "./domHarness";

const cleanups: Array<() => Promise<void>> = [];
afterEach(async () => {
  while (cleanups.length) await cleanups.pop()!();
});

describe("Randomizer in sample mode", () => {
  test("says it spins among the sample's games and how to spin from all of IGDB", async () => {
    const api = fakeApiClient({
      randomizerOptions: async () => ({ genres: [{ id: 12, name: "Role-playing (RPG)" }], themes: [], gameModes: [], perspectives: [], platforms: [], tags: [], sample: true })
    });
    const view = await renderInteractive(<AppShell apiBaseUrl="http://unused" api={api} />);
    cleanups.push(view.cleanup);

    await click(getButton(view.container, "Randomizer"));
    // The Randomizer's code loads on first visit.
    for (let tries = 0; tries < 50 && !view.container.querySelector(".randomizer-empty"); tries++) {
      await act(async () => { await new Promise(resolve => setTimeout(resolve, 20)); });
    }

    expect(view.container.textContent).toContain("Sample mode: spins pick from 267 games of the sample library");
    expect(getButton(view.container, "Spin").disabled).toBe(false);
  });
});
