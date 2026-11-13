// Chapter navigation for Year in Review, as a pure reducer. The view turns DOM events into these events
// (time passed in, never read) and applies the result, so every rule is testable without a DOM or timers.

export const NAVIGATION = {
  // Wheel delta that carries on into the next chapter...
  pullThreshold: 160,
  // ...if it builds within this window.
  pullWindowMs: 600,
  // The scroll must have been still this long at the edge before pull counts, so a fling never skips.
  restMs: 150,
  // After a chapter change, wheel input is ignored until the wheel has been quiet this long (momentum).
  cooldownQuietMs: 400
} as const;

export interface NavigationState {
  count: number;
  chapter: number;
  // Where the entering chapter's scroll starts, and which side it slides in from.
  landAt: "top" | "bottom";
  enterFrom: "left" | "right";
  // Bumped on every chapter change.
  changes: number;
  // Progress toward carrying on, for the hint at the edge; null when not pulling.
  pull: { direction: 1 | -1; progress: number } | null;
  pullAmount: number;
  pullStartedAt: number;
  // When the scroll counts as at rest; null until the chapter has settled or the scroll stopped.
  restFrom: number | null;
  cooling: boolean;
  lastWheelAt: number;
}

export type NavigationEvent =
  | { type: "wheel"; deltaY: number; atTop: boolean; atBottom: boolean; now: number }
  | { type: "scrolled"; now: number }
  | { type: "settled"; now: number }
  | { type: "key"; key: string; atTop: boolean; atBottom: boolean }
  | { type: "tab"; index: number };

export function initialNavigation(count: number, chapter = 0): NavigationState {
  return { count, chapter: Math.max(0, Math.min(count - 1, chapter)), landAt: "top", enterFrom: "right", changes: 0, pull: null, pullAmount: 0, pullStartedAt: 0, restFrom: null, cooling: false, lastWheelAt: -Infinity };
}

function goTo(state: NavigationState, index: number, landAt: "top" | "bottom", now = -Infinity): NavigationState {
  const target = Math.max(0, Math.min(state.count - 1, index));
  if (target === state.chapter) return state;
  return {
    ...state,
    chapter: target,
    landAt,
    enterFrom: target > state.chapter ? "right" : "left",
    changes: state.changes + 1,
    pull: null,
    pullAmount: 0,
    restFrom: null,
    cooling: true,
    lastWheelAt: now
  };
}

const stopPulling = (state: NavigationState): NavigationState => (state.pull || state.pullAmount ? { ...state, pull: null, pullAmount: 0 } : state);

export function navigate(state: NavigationState, event: NavigationEvent): NavigationState {
  switch (event.type) {
    case "tab":
      return goTo(state, event.index, "top");
    case "settled":
      return { ...state, restFrom: event.now };
    case "scrolled":
      return { ...stopPulling(state), restFrom: event.now + NAVIGATION.restMs };
    case "key":
      if (event.key === "ArrowRight") return goTo(state, state.chapter + 1, "top");
      if (event.key === "ArrowLeft") return goTo(state, state.chapter - 1, "top");
      if (event.key === "Home") return goTo(state, 0, "top");
      if (event.key === "End") return goTo(state, state.count - 1, "top");
      if ((event.key === "PageDown" || event.key === " ") && event.atBottom) return goTo(state, state.chapter + 1, "top");
      if (event.key === "PageUp" && event.atTop) return goTo(state, state.chapter - 1, "bottom");
      return state;
    case "wheel":
      return wheel(state, event);
  }
}

function wheel(state: NavigationState, event: Extract<NavigationEvent, { type: "wheel" }>): NavigationState {
  if (state.cooling) {
    if (event.now - state.lastWheelAt < NAVIGATION.cooldownQuietMs) return { ...state, lastWheelAt: event.now };
    state = { ...state, cooling: false };
  }
  state = { ...state, lastWheelAt: event.now };
  if (!event.deltaY) return state;
  const direction = event.deltaY > 0 ? 1 : -1;
  const atEdge = direction === 1 ? event.atBottom : event.atTop;
  const target = state.chapter + direction;
  const atRest = state.restFrom !== null && event.now >= state.restFrom;
  if (!atEdge || !atRest || target < 0 || target >= state.count) return stopPulling(state);

  const continuing = state.pull?.direction === direction && event.now - state.pullStartedAt <= NAVIGATION.pullWindowMs;
  const pullAmount = (continuing ? state.pullAmount : 0) + Math.abs(event.deltaY);
  const pullStartedAt = continuing ? state.pullStartedAt : event.now;
  if (pullAmount >= NAVIGATION.pullThreshold) return goTo(state, target, direction === 1 ? "top" : "bottom", event.now);
  return { ...state, pullAmount, pullStartedAt, pull: { direction, progress: pullAmount / NAVIGATION.pullThreshold } };
}
