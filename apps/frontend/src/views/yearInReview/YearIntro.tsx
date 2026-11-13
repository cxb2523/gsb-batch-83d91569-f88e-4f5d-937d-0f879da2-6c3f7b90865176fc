import { useEffect, useRef, useState, type CSSProperties } from "react";
import type { YearInReviewSummary } from "../../../../../shared/types";
import { igdbCoverSrc } from "../../artwork";
import { plural } from "./parts";

// How long the opening plays before it opens up onto the first chapter, and how long that reveal takes.
const INTRO_REVEAL_AT_MS = 3000;
const INTRO_MS = 3700;

// The opening, like the Wrapped recaps: colour blobs, the year's digits slamming in, a band of the year's
// covers, the count, then a widening hole onto the first chapter. A click or any key skips it (the capture
// listener runs before the view's own keys).
// `onOpen` fires when it starts opening up (or is skipped), `onDone` once it is gone.
export function YearIntro({ summary, onOpen, onDone }: { summary: YearInReviewSummary; onOpen: () => void; onDone: () => void }) {
  const [leaving, setLeaving] = useState(false);
  const calls = useRef({ onOpen, onDone });
  calls.current = { onOpen, onDone };
  const finish = () => {
    calls.current.onOpen();
    calls.current.onDone();
  };
  useEffect(() => {
    const reveal = setTimeout(() => {
      setLeaving(true);
      calls.current.onOpen();
    }, INTRO_REVEAL_AT_MS);
    const end = setTimeout(() => calls.current.onDone(), INTRO_MS);
    // A key only skips the opening; marked handled so it doesn't also turn a chapter or leave.
    // Shortcuts and Tab pass through untouched.
    const skip = (event: KeyboardEvent) => {
      if (event.ctrlKey || event.altKey || event.metaKey || event.key === "Tab") return;
      event.preventDefault();
      finish();
    };
    window.addEventListener("keydown", skip, true);
    return () => {
      clearTimeout(reveal);
      clearTimeout(end);
      window.removeEventListener("keydown", skip, true);
    };
  }, []);
  const covers = summary.games.filter(game => game.coverImageId).slice(0, 14);
  return (
    <div className={`yir-intro${leaving ? " is-leaving" : ""}`} aria-hidden="true" onClick={finish}>
      <div className="yir-intro__blobs"><span /><span /><span /></div>
      {covers.length > 0 && (
        <div className="yir-intro__band">
          <div className="yir-intro__strip">
            {[...covers, ...covers].map((game, index) => <img key={index} src={igdbCoverSrc(game.coverImageId!)} alt="" draggable={false} />)}
          </div>
        </div>
      )}
      <div className="yir-intro__words">
        <p className="yir-intro__kicker">Your</p>
        <p className="yir-intro__year">
          {String(summary.year).split("").map((digit, index) => <span key={index} style={{ "--d": index } as CSSProperties}>{digit}</span>)}
        </p>
        <p className="yir-intro__line">in games</p>
        <p className="yir-intro__count"><b>{plural(summary.count, "game")}</b> finished{summary.inProgress ? " so far" : ""}. Let's look back.</p>
      </div>
      <span className="yir-intro__skip">Click or press any key to skip</span>
    </div>
  );
}
