import { useEffect, useLayoutEffect, useRef, useState, type CSSProperties, type PointerEvent, type ReactNode } from "react";
import type { YearInReviewGame, YearInReviewSettingsPatch, YearInReviewSummary } from "../../../../shared/types";
import { cachedCoverSrc } from "../artwork";
import { Button } from "../ui/Button";
import type { YearInReviewPlace, YearInReviewWorkflow } from "../useYearInReviewWorkflow";
import { initialNavigation, navigate, type NavigationEvent, type NavigationState } from "../yearInReviewNavigation";
import { resolveShelf, ShelfReveal } from "./yearInReview/GameShelf";
import { GotyChapter } from "./yearInReview/GotyChapter";
import { OverviewChapter } from "./yearInReview/OverviewChapter";
import { drawPoster, POSTER_FORMATS, type PosterOrientation } from "./yearInReview/poster";
import { canAnimate, prefersReducedMotion } from "../motion";
import { OpenGame, ShelfControl, useReveal, type ShelfKey } from "./yearInReview/parts";
import { RatingsChapter } from "./yearInReview/RatingsChapter";
import { RealmParticles, RealmScenes, type ParticleMode } from "./yearInReview/RealmScenes";
import { TasteChapter } from "./yearInReview/TasteChapter";
import { ThemePlayer } from "./yearInReview/ThemePlayer";
import { TimingChapter } from "./yearInReview/TimingChapter";
import { YearIntro } from "./yearInReview/YearIntro";
import "./yearInReview/realmFonts.css";
import "./yearInReview/yearInReview.css";

interface ChapterContext {
  summary: YearInReviewSummary;
  saveSettings: (patch: YearInReviewSettingsPatch) => Promise<string | null>;
  playTheme: () => void;
  stopTheme: () => void;
  themePlaying: boolean;
}

// Each chapter is a realm with its own scene, colours, card style and lettering (keyed by `key` in the CSS).
type RealmKey = "overview" | "taste" | "ratings" | "timing" | "goty";

interface Realm {
  name: string;
  numeral: string;
  // No heading: the chapter draws its own (the GOTY finale).
  heading: ((summary: YearInReviewSummary) => string) | null;
  lead: string;
  particles: ParticleMode;
  wipeColor: string;
  icon: ReactNode;
}

interface Chapter {
  key: RealmKey;
  title: string;
  realm: Realm;
  render: (context: ChapterContext) => ReactNode;
}

const sigil = { className: "yir-tab__icon", viewBox: "0 0 26 26", "aria-hidden": true } as const;

export const CHAPTERS: Chapter[] = [
  {
    key: "overview",
    title: "Overview",
    realm: { name: "The Atlas", numeral: "I", heading: summary => `The Voyage of ${summary.year}`, lead: "Your year, charted as a sea voyage. Each port on the map is a month; the bigger the port, the more games you finished there.", particles: "stars", wipeColor: "#e8c26a", icon: <svg {...sigil} fill="none" stroke="currentColor" strokeWidth="1.5"><circle cx="13" cy="13" r="11" /><path d="M13 3 l3 10 -3 10 -3 -10z" fill="currentColor" /></svg> },
    render: ({ summary }) => <OverviewChapter summary={summary} />
  },
  {
    key: "taste",
    title: "Taste",
    realm: { name: "The Grimoire", numeral: "II", heading: () => "The Grimoire of Taste", lead: "The schools of play you studied most. Open any page to see which games are bound inside it.", particles: "motes", wipeColor: "#3fa66f", icon: <svg {...sigil} fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M2 6c4-2 8-1 11 2 3-3 7-4 11-2v15c-4-2-8-1-11 2-3-3-7-4-11-2z" /><path d="M13 8v15" /></svg> },
    render: ({ summary }) => <TasteChapter summary={summary} />
  },
  {
    key: "ratings",
    title: "Ratings",
    realm: { name: "The Forge", numeral: "III", heading: () => "The Forge of Judgement", lead: "Every game was hammered out on the anvil and given its mark. Strike a rating to see what was forged at it.", particles: "embers", wipeColor: "#ff7a2a", icon: <svg {...sigil} fill="currentColor"><path d="M3 12h17c2 0 4-1 5-2-1 3-3 4-5 4h-3l-1 3 2 2v2H7v-2l2-2-1-3H5c-1 0-2-1-2-2z" /></svg> },
    render: ({ summary }) => <RatingsChapter summary={summary} />
  },
  {
    key: "timing",
    title: "Timing & Habits",
    realm: { name: "The Astrolabe", numeral: "IV", heading: () => "The Astrolabe of Seasons", lead: "The great dial points at your busiest month. Pick any month to see what you finished under its stars.", particles: "stars", wipeColor: "#8f6cff", icon: <svg {...sigil} fill="none" stroke="currentColor" strokeWidth="1.5"><circle cx="13" cy="14" r="10" /><circle cx="13" cy="14" r="6" /><path d="M13 14l6-6M13 1v3" /></svg> },
    render: ({ summary }) => <TimingChapter summary={summary} />
  },
  {
    key: "goty",
    title: "Game of the Year",
    realm: { name: "The Throne", numeral: "V", heading: null, lead: "", particles: "dust", wipeColor: "#f3d27a", icon: <svg {...sigil} fill="currentColor"><path d="M2 21 L1 6 L8 13 L13 3 L18 13 L25 6 L24 21 Z" /></svg> },
    render: ({ summary, saveSettings, playTheme, stopTheme, themePlaying }) => <GotyChapter summary={summary} saveSettings={saveSettings} onPlayTheme={playTheme} onStopTheme={stopTheme} themePlaying={themePlaying} />
  }
];

const SLIDE_MS = 320;
const FADE_MS = 120;
// The colour band that sweeps across on a chapter change, in the colour of the chapter it brings in.
const WIPE_MS = 900;

const isTyping = (target: EventTarget | null) => {
  const element = target as HTMLElement | null;
  if (!element || typeof element.closest !== "function") return false;
  return ["INPUT", "TEXTAREA", "SELECT"].includes(element.tagName) || element.isContentEditable || Boolean(element.closest("[data-yir-keys='off']"));
};

// Space on a focused button or link presses it, so it isn't a page turn.
const pressesControl = (event: KeyboardEvent) => {
  const element = event.target as HTMLElement | null;
  return event.key === " " && typeof element?.closest === "function" && Boolean(element.closest("button, a[href]"));
};

// Full screen over the whole app window. Escape (with nothing open) or Leave goes back through `onExit`.
export function YearInReviewView({ workflow, apiBaseUrl, onOpenGame, onExit }: { workflow: YearInReviewWorkflow; apiBaseUrl?: string; onOpenGame?: (id: string) => void; onExit?: () => void }) {
  const { years, year, summary, status, place, themeAutoplay, actions } = workflow;
  // The theme player belongs to the view, not the GOTY chapter, so it keeps playing across chapter changes.
  // It follows the year on screen (another year plays its own theme, or nothing). With autoplay on it starts
  // by itself; otherwise it waits for Play. Play or Stop holds for that year and link. Leaving Year in Review
  // unmounts it.
  const [choice, setChoice] = useState<{ year: number; videoId: string; playing: boolean } | null>(null);
  const musicVideoId = summary?.goty?.musicVideoId ?? null;
  const chosen = choice && summary && choice.year === summary.year && choice.videoId === musicVideoId ? choice.playing : themeAutoplay;
  const themeVideoId = summary && musicVideoId && chosen ? musicVideoId : null;
  const scenes = useRef<HTMLDivElement>(null);
  const [chapterIndex, setChapterIndex] = useState(0);
  // Save as image: a poster of every game finished this year, horizontal or vertical. Desktop only.
  const [saveMenu, setSaveMenuState] = useState(false);
  const saveMenuRef = useRef(false);
  const setSaveMenu = (open: boolean) => {
    saveMenuRef.current = open;
    setSaveMenuState(open);
  };
  const [saveNote, setSaveNote] = useState<string | null>(null);
  const saveBridge = typeof window === "undefined" ? undefined : window.releaseTracker?.saveImage;
  const savePoster = async (orientation: PosterOrientation) => {
    setSaveMenu(false);
    if (!saveBridge || !summary) return;
    setSaveNote("Drawing…");
    try {
      const base = apiBaseUrl || window.location.origin;
      const png = await drawPoster({ summary, orientation, coverSrc: imageId => cachedCoverSrc(imageId, base) });
      const result = await saveBridge(png, `Year in Review ${summary.year} - ${orientation === "horizontal" ? "Horizontal" : "Vertical"}`);
      setSaveNote(result.ok ? "Saved" : result.canceled ? null : result.error ?? "Couldn't save the image");
    } catch (error) {
      setSaveNote(error instanceof Error ? error.message : "Couldn't save the image");
    }
  };
  const context: ChapterContext | null = summary ? {
    summary,
    saveSettings: actions.saveSettings,
    playTheme: () => { if (musicVideoId) setChoice({ year: summary.year, videoId: musicVideoId, playing: true }); },
    stopTheme: () => { if (musicVideoId) setChoice({ year: summary.year, videoId: musicVideoId, playing: false }); },
    themePlaying: Boolean(themeVideoId)
  } : null;
  const hasChapters = Boolean(context && context.summary.count > 0);

  // The opening plays once per year you open, not when coming back from a game's page. It "plays" until it
  // starts opening up onto the chapter (the heading and cards animate in then), and is gone once that ends.
  const [intro, setIntro] = useState<{ year: number; opening: boolean } | null>(null);
  const introShown = useRef<number | null>(null);
  useEffect(() => {
    if (!summary || summary.count === 0 || introShown.current === summary.year) return;
    introShown.current = summary.year;
    if (canAnimate() && place?.year !== summary.year) setIntro({ year: summary.year, opening: false });
  }, [summary?.year, summary?.count]);
  const introShowing = intro !== null && intro.year === summary?.year;
  const introPlaying = introShowing && !intro.opening;
  const chapter = (hasChapters && CHAPTERS[chapterIndex]) || CHAPTERS[0];

  // Escape closes the save choice, else leaves, unless the chapter stage used it first (closing a shelf) or it
  // was typed into a field. On window, so it always hears the key after the stage's document listener.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Escape" || event.defaultPrevented || isTyping(event.target)) return;
      if (saveMenuRef.current) setSaveMenu(false);
      else onExit?.();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onExit]);

  // The scene leans a little away from the pointer.
  const lean = (event: PointerEvent<HTMLElement>) => {
    const element = scenes.current;
    if (!element || prefersReducedMotion()) return;
    const x = event.clientX / window.innerWidth - 0.5;
    const y = event.clientY / window.innerHeight - 0.5;
    element.style.transform = `translate(${(-x * 16).toFixed(1)}px, ${(-y * 10).toFixed(1)}px)`;
  };

  return (
    <>
      <section className={`yir${introPlaying ? " yir--intro" : ""}`} data-realm={chapter.key} onPointerMove={lean}>
        {hasChapters && context && <RealmScenes summary={context.summary} scenes={scenes} />}
        <RealmParticles mode={chapter.realm.particles} />
        <div className="yir-scrim" aria-hidden="true" />
        <header className="yir-header">
          <h1>Your <em>{year ?? ""}</em> in games</h1>
          {summary?.inProgress && <span className="yir-badge">so far</span>}
          <label className="yir-year">
            <span className="sr-only">Year</span>
            <select aria-label="Year" value={year ?? ""} onChange={event => actions.selectYear(Number(event.target.value))} disabled={!years.length}>
              {years.map(entry => <option key={entry.year} value={entry.year}>{entry.year}{entry.inProgress ? " (so far)" : ""}</option>)}
            </select>
          </label>
          {saveBridge && summary && summary.count > 0 && (
            <div className="yir-header__actions">
              {saveNote && <span className="yir-header__note" role="status">{saveNote}</span>}
              <div className="yir-save">
                <Button small onClick={() => setSaveMenu(!saveMenu)} aria-expanded={saveMenu}>Save as image</Button>
                {saveMenu && (
                  <div className="yir-save__menu" role="menu" aria-label="Save as image">
                    <p className="yir-save__intro">A poster of all {summary.count} games you finished in {summary.year}</p>
                    {(["horizontal", "vertical"] as const).map(orientation => (
                      <button key={orientation} type="button" role="menuitem" className="yir-save__choice" onClick={() => void savePoster(orientation)}>
                        <span className={`yir-save__shape yir-save__shape--${orientation}`} aria-hidden="true" />
                        <span className="yir-save__label">{POSTER_FORMATS[orientation].label}<small>{POSTER_FORMATS[orientation].detail}</small></span>
                      </button>
                    ))}
                  </div>
                )}
              </div>
            </div>
          )}
          {onExit && <button type="button" className="yir-leave" onClick={onExit} title="Leave Year in Review (Esc)">✕ Leave</button>}
        </header>
        {!context && <div className="state">{status === "error" ? "Year in Review couldn't load." : "Loading your year..."}</div>}
        {context && context.summary.count === 0 && (
          <div className="yir-empty">
            <h2>No finished games recorded for {context.summary.year}</h2>
            <p>Games you finish show up here once they're in the Completed Library with a {context.summary.year} completion date.</p>
          </div>
        )}
        {context && context.summary.count > 0 && (
          <ChapterStage
            key={context.summary.year}
            context={context}
            startAt={place?.year === context.summary.year ? place : null}
            onStarted={actions.forgetPlace}
            onChapter={setChapterIndex}
            introPlaying={introPlaying}
            onOpenGame={onOpenGame && ((game, where) => {
              actions.rememberPlace({ year: context.summary.year, ...where });
              onOpenGame(game.id);
            })}
          />
        )}
        {introShowing && context && <YearIntro summary={context.summary} onOpen={() => setIntro(current => current && { ...current, opening: true })} onDone={() => setIntro(null)} />}
      </section>
      {themeVideoId && context && <ThemePlayer videoId={themeVideoId} onStop={context.stopTheme} />}
    </>
  );
}

function ChapterStage({ context, startAt, onStarted, onChapter, introPlaying = false, onOpenGame }: {
  context: ChapterContext;
  // Where to land when coming back from a game's page; null starts at Overview.
  startAt: YearInReviewPlace | null;
  onStarted: () => void;
  onChapter: (index: number) => void;
  // While the opening plays, the cards wait to cascade in until it has opened up.
  introPlaying?: boolean;
  onOpenGame?: (game: YearInReviewGame, where: Omit<YearInReviewPlace, "year">) => void;
}) {
  const [nav, setNav] = useState<NavigationState>(() => initialNavigation(CHAPTERS.length, startAt?.chapter));
  const navRef = useRef(nav);
  const scroller = useRef<HTMLDivElement>(null);
  const [leaving, setLeaving] = useState<{ index: number; changes: number } | null>(null);
  const [wipe, setWipe] = useState<{ changes: number; color: string; from: "left" | "right" } | null>(null);
  // The category whose games are unrolled under the cards; closed by Escape, its Close button, or a chapter change.
  const [shelf, setShelfState] = useState<ShelfKey | null>(() => (startAt?.shelf && resolveShelf(context.summary, startAt.shelf) ? startAt.shelf : null));
  // Scroll to the shelf when a click opens it or it's restored; not every time it re-renders.
  const [scrollToShelf, setScrollToShelf] = useState(Boolean(shelf));
  const shelfRef = useRef(shelf);
  const setShelf = (next: ShelfKey | null) => {
    shelfRef.current = next;
    setShelfState(next);
  };
  const toggleShelf = (key: ShelfKey) => {
    setScrollToShelf(true);
    setShelf(shelfRef.current === key ? null : key);
  };
  const previousChapter = useRef(nav.chapter);

  // Applies an event; true when it changed chapter (so the key or wheel shouldn't also scroll).
  const apply = (event: NavigationEvent) => {
    const next = navigate(navRef.current, event);
    if (next === navRef.current) return false;
    const changed = next.changes !== navRef.current.changes;
    navRef.current = next;
    setNav(next);
    return changed;
  };

  const edges = () => {
    const element = scroller.current;
    if (!element) return { atTop: true, atBottom: true };
    return { atTop: element.scrollTop <= 1, atBottom: element.scrollTop + element.clientHeight >= element.scrollHeight - 1 };
  };

  useLayoutEffect(() => onChapter(nav.chapter), [nav.chapter]);

  // The chapter that just slid in lands at its top or bottom, then counts as at rest once the slide ends.
  useLayoutEffect(() => {
    if (nav.chapter === previousChapter.current) {
      const timeout = setTimeout(() => apply({ type: "settled", now: performance.now() }), SLIDE_MS);
      return () => clearTimeout(timeout);
    }
    setLeaving({ index: previousChapter.current, changes: nav.changes });
    if (canAnimate()) setWipe({ changes: nav.changes, color: CHAPTERS[nav.chapter].realm.wipeColor, from: nav.enterFrom });
    previousChapter.current = nav.chapter;
    setShelf(null);
    const element = scroller.current;
    if (element) element.scrollTop = nav.landAt === "bottom" ? element.scrollHeight : 0;
    const timeout = setTimeout(() => {
      setLeaving(null);
      apply({ type: "settled", now: performance.now() });
    }, prefersReducedMotion() ? FADE_MS : SLIDE_MS);
    return () => clearTimeout(timeout);
  }, [nav.changes]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.defaultPrevented || event.ctrlKey || event.metaKey || event.altKey || isTyping(event.target) || pressesControl(event)) return;
      if (event.key === "Escape") {
        // Escape closes an open shelf first; the view leaves Year in Review on the next one.
        if (shelfRef.current) {
          setShelf(null);
          event.preventDefault();
        }
        return;
      }
      if (apply({ type: "key", key: event.key, ...edges() })) event.preventDefault();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

  useEffect(() => {
    if (!wipe) return;
    const timeout = setTimeout(() => setWipe(null), WIPE_MS);
    return () => clearTimeout(timeout);
  }, [wipe?.changes]);

  useReveal(scroller, nav.changes, introPlaying);

  useEffect(() => { if (startAt) onStarted(); }, []);
  const openGame = onOpenGame ? (game: YearInReviewGame) => onOpenGame(game, { chapter: navRef.current.chapter, shelf: shelfRef.current }) : null;

  const chapter = CHAPTERS[nav.chapter];
  const next = CHAPTERS[nav.chapter + 1];
  const motion = prefersReducedMotion() ? "fade" : nav.enterFrom;
  const leavingChapter = leaving ? CHAPTERS[leaving.index] : null;
  const openShelf = resolveShelf(context.summary, shelf);

  return (
    <OpenGame.Provider value={openGame}><ShelfControl.Provider value={{ current: shelf, toggle: toggleShelf }}>
      {wipe && <div key={`wipe-${wipe.changes}`} className={`yir-wipe yir-wipe--from-${wipe.from}`} style={{ "--wipe": wipe.color } as CSSProperties} aria-hidden="true" />}
      <nav className="yir-tabs" role="tablist" aria-label="Chapters">
        {CHAPTERS.map((item, index) => (
          <button key={item.key} type="button" role="tab" aria-selected={index === nav.chapter} className={`yir-tab yir-tab--${item.key}${index === nav.chapter ? " active" : ""}`} data-realm-name={item.realm.name} onClick={() => apply({ type: "tab", index })}>
            {item.realm.icon}{item.title}
          </button>
        ))}
      </nav>
      <div className="yir-stage">
        {leavingChapter && (
          <div key={`leaving-${leaving!.changes}`} className={`yir-chapter yir-chapter--leave-${motion}`} aria-hidden="true">
            <ChapterBody chapter={leavingChapter} context={context} />
          </div>
        )}
        <div
          key={`chapter-${nav.chapter}`}
          ref={scroller}
          className={`yir-chapter${leaving ? ` yir-chapter--enter-${motion}` : ""}`}
          role="tabpanel"
          aria-label={chapter.title}
          onScroll={() => apply({ type: "scrolled", now: performance.now() })}
          onWheel={event => apply({ type: "wheel", deltaY: event.deltaY, ...edges(), now: performance.now() })}
        >
          {nav.pull?.direction === -1 && <div className="yir-carry yir-carry--up"><span className="yir-carry__fill" style={{ width: `${Math.round(nav.pull.progress * 100)}%` }} />Keep scrolling for {CHAPTERS[nav.chapter - 1]?.realm.name}</div>}
          <ChapterBody chapter={chapter} context={context}>
            {openShelf && <ShelfReveal shelf={openShelf} onClose={() => setShelf(null)} scrollIntoView={scrollToShelf} />}
          </ChapterBody>
          <div className="yir-carry">
            {next
              ? <><span className="yir-carry__fill" style={{ width: nav.pull?.direction === 1 ? `${Math.round(nav.pull.progress * 100)}%` : "0%" }} />Keep scrolling for {next.realm.name} →</>
              : <>That's your {context.summary.year}</>}
          </div>
        </div>
      </div>
    </ShelfControl.Provider></OpenGame.Provider>
  );
}

function ChapterBody({ chapter, context, children }: { chapter: Chapter; context: ChapterContext; children?: ReactNode }) {
  const { realm } = chapter;
  return (
    <div className={`yir-chapter__content yir-chapter__content--${chapter.key}`}>
      {realm.heading ? (
        <header className="yir-realm-head">
          <p className="yir-realm-head__eyebrow">Chapter {realm.numeral} · {realm.name}</p>
          <h2 className="yir-chapter__title">{realm.heading(context.summary)}</h2>
          <p className="yir-realm-head__lead">{realm.lead}</p>
        </header>
      ) : <h2 className="sr-only">{chapter.title}</h2>}
      {chapter.render(context)}
      {children}
    </div>
  );
}
