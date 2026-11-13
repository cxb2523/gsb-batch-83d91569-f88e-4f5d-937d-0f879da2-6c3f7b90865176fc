import { describe, expect, test } from "vitest";
import { initialNavigation, navigate, NAVIGATION, type NavigationEvent, type NavigationState } from "../../apps/frontend/src/yearInReviewNavigation";

const run = (events: NavigationEvent[], start: NavigationState = initialNavigation(5)) => events.reduce(navigate, start);
const wheel = (deltaY: number, now: number, edges: { atTop?: boolean; atBottom?: boolean } = { atBottom: deltaY > 0, atTop: deltaY < 0 }): NavigationEvent =>
  ({ type: "wheel", deltaY, atTop: Boolean(edges.atTop), atBottom: Boolean(edges.atBottom), now });

describe("Year in Review chapter navigation", () => {
  test("starts on the first chapter", () => {
    expect(initialNavigation(5)).toMatchObject({ chapter: 0, landAt: "top", enterFrom: "right" });
  });

  test("tabs and arrow keys change chapter, sliding in from the side of the move", () => {
    const tabbed = run([{ type: "tab", index: 3 }]);
    expect(tabbed).toMatchObject({ chapter: 3, enterFrom: "right", landAt: "top" });
    expect(navigate(tabbed, { type: "key", key: "ArrowLeft", atTop: false, atBottom: false })).toMatchObject({ chapter: 2, enterFrom: "left" });
    expect(navigate(tabbed, { type: "key", key: "ArrowRight", atTop: false, atBottom: false })).toMatchObject({ chapter: 4, enterFrom: "right" });
    expect(navigate(tabbed, { type: "key", key: "Home", atTop: false, atBottom: false }).chapter).toBe(0);
    expect(navigate(tabbed, { type: "key", key: "End", atTop: false, atBottom: false }).chapter).toBe(4);
  });

  test("chapters don't wrap around", () => {
    expect(run([{ type: "key", key: "ArrowLeft", atTop: true, atBottom: true }]).chapter).toBe(0);
    expect(run([{ type: "tab", index: 4 }, { type: "key", key: "ArrowRight", atTop: true, atBottom: true }]).chapter).toBe(4);
  });

  test("pulling down past the bottom at rest carries on into the next chapter, at its top", () => {
    const state = run([{ type: "scrolled", now: 1000 }, wheel(100, 1200), wheel(100, 1250)]);
    expect(state).toMatchObject({ chapter: 1, landAt: "top", enterFrom: "right" });
  });

  test("the pull shows as progress before it is enough", () => {
    const state = run([{ type: "scrolled", now: 1000 }, wheel(80, 1200)]);
    expect(state.chapter).toBe(0);
    expect(state.pull).toEqual({ direction: 1, progress: 80 / NAVIGATION.pullThreshold });
  });

  test("a fling that is still scrolling never builds pull", () => {
    const state = run([{ type: "scrolled", now: 1000 }, wheel(200, 1050), { type: "scrolled", now: 1100 }, wheel(200, 1120)]);
    expect(state.chapter).toBe(0);
    expect(state.pull).toBeNull();
  });

  test("pull only counts at the edge it points to", () => {
    const state = run([{ type: "scrolled", now: 1000 }, wheel(200, 1200, { atTop: true, atBottom: false })]);
    expect(state.chapter).toBe(0);
    expect(state.pull).toBeNull();
  });

  test("pull that builds too slowly starts over", () => {
    const state = run([{ type: "scrolled", now: 1000 }, wheel(100, 1200), wheel(100, 1900)]);
    expect(state.chapter).toBe(0);
    expect(state.pull?.progress).toBeCloseTo(100 / NAVIGATION.pullThreshold);
  });

  test("pulling up at the top goes back and lands at the previous chapter's bottom", () => {
    const state = run([{ type: "tab", index: 2 }, { type: "settled", now: 1000 }, wheel(-200, 1100)]);
    expect(state).toMatchObject({ chapter: 1, landAt: "bottom", enterFrom: "left" });
  });

  test("a short chapter carries on with one pull once it has slid in", () => {
    const shortChapter = { atTop: true, atBottom: true };
    expect(run([{ type: "settled", now: 1000 }, wheel(200, 1010, shortChapter)]).chapter).toBe(1);
    expect(run([{ type: "tab", index: 2 }, { type: "settled", now: 1000 }, wheel(-200, 1010, shortChapter)]).chapter).toBe(1);
  });

  test("momentum after a chapter change is ignored until the wheel has been quiet", () => {
    const shortChapter = { atTop: true, atBottom: true };
    const moved = run([{ type: "settled", now: 1000 }, wheel(200, 1010, shortChapter)]);
    expect(moved.chapter).toBe(1);
    const tail = run([{ type: "settled", now: 1400 }, wheel(200, 1100, shortChapter), wheel(200, 1300, shortChapter), wheel(200, 1500, shortChapter)], moved);
    expect(tail.chapter).toBe(1);
    const fresh = navigate(tail, wheel(200, 2000, shortChapter));
    expect(fresh.chapter).toBe(2);
  });

  test("the last chapter doesn't advance", () => {
    const state = run([{ type: "tab", index: 4 }, { type: "settled", now: 1000 }, wheel(500, 1100)]);
    expect(state.chapter).toBe(4);
    expect(state.pull).toBeNull();
  });

  test("PageDown and Space carry on only at the bottom; PageUp only at the top", () => {
    expect(run([{ type: "key", key: "PageDown", atTop: false, atBottom: false }]).chapter).toBe(0);
    expect(run([{ type: "key", key: "PageDown", atTop: false, atBottom: true }]).chapter).toBe(1);
    expect(run([{ type: "key", key: " ", atTop: false, atBottom: true }]).chapter).toBe(1);
    expect(run([{ type: "tab", index: 2 }, { type: "key", key: "PageUp", atTop: true, atBottom: false }])).toMatchObject({ chapter: 1, landAt: "bottom" });
  });

  test("every change counts, so the view can land the new chapter", () => {
    expect(run([{ type: "tab", index: 1 }, { type: "tab", index: 1 }, { type: "tab", index: 2 }]).changes).toBe(2);
  });
});
