export const prefersReducedMotion = () => {
  try { return Boolean(globalThis.matchMedia?.("(prefers-reduced-motion: reduce)").matches); } catch { return false; }
};

// Big motion needs a real frame loop, and never runs when the system asks for reduced motion.
export const canAnimate = () => typeof window !== "undefined" && typeof window.requestAnimationFrame === "function" && !prefersReducedMotion();
