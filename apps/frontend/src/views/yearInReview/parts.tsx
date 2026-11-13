import { createContext, useContext, useEffect, useRef, type CSSProperties, type ReactNode, type RefObject } from "react";
import type { YearInReviewGame, YearInReviewShare } from "../../../../../shared/types";
import { igdbCoverSrc, igdbCoverSrcSet } from "../../artwork";
import { prefersReducedMotion } from "../../motion";

// Provided by the chapter stage: opens a game's Completed Library page. Without it (server render,
// isolated chapter tests) games render as plain, non-clickable rows and covers.
export const OpenGame = createContext<((game: YearInReviewGame) => void) | null>(null);

// A category's game list; see resolveShelf in GameShelf for the keys.
export type ShelfKey = string;

// Provided by the chapter stage: which shelf is open, and how to open or close one. Without it (server render,
// isolated chapter tests) categories render as plain, non-clickable text.
export const ShelfControl = createContext<{ current: ShelfKey | null; toggle: (key: ShelfKey) => void } | null>(null);

// The props that make a category open its shelf, or null when there's no stage.
export function useShelfButton(key: ShelfKey) {
  const control = useContext(ShelfControl);
  if (!control) return null;
  return { type: "button" as const, "aria-pressed": control.current === key, onClick: () => control.toggle(key) };
}

export function ShelfRow({ shelf, className, ariaLabel, children }: { shelf?: ShelfKey; className: string; ariaLabel: string; children: ReactNode }) {
  const button = useShelfButton(shelf ?? "");
  return shelf && button
    ? <button {...button} className={className} aria-label={ariaLabel}>{children}</button>
    : <div className={className}>{children}</div>;
}

// Without an opener, children sit in a div with `fallbackClassName`, or bare when it is not given.
export function OpenGameButton({ game, className, fallbackClassName, children }: { game: YearInReviewGame; className: string; fallbackClassName?: string; children: ReactNode }) {
  const open = useContext(OpenGame);
  if (open) return <button type="button" className={className} aria-label={`Open ${game.title}`} onClick={() => open(game)}>{children}</button>;
  return fallbackClassName ? <div className={fallbackClassName}>{children}</div> : <>{children}</>;
}

export const MONTH_NAMES = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];

export const percent = (share: number) => `${Math.round(share * 100)}%`;
export const plural = (count: number, one: string, many = `${one}s`) => `${count} ${count === 1 ? one : many}`;
export const formatRating = (value: number) => (Number.isInteger(value) ? String(value) : value.toFixed(1));

// Cards render visible. Only where an IntersectionObserver exists are the ones below the fold held back
// and revealed as they scroll in, so tests and first paint always see the content. `hold` keeps every card
// back (the opening is playing over them); letting go cascades the visible ones in.
export function useReveal(container: RefObject<HTMLElement | null>, key: unknown, hold = false) {
  useEffect(() => {
    const root = container.current;
    if (!root || typeof IntersectionObserver === "undefined" || prefersReducedMotion()) return;
    const cards = [...root.querySelectorAll<HTMLElement>(".yir-card")];
    if (hold) {
      for (const card of cards) card.classList.add("is-pending");
      return () => { for (const card of cards) card.classList.remove("is-pending"); };
    }
    const observer = new IntersectionObserver(entries => {
      for (const entry of entries) {
        if (!entry.isIntersecting) continue;
        entry.target.classList.remove("is-pending");
        observer.unobserve(entry.target);
      }
    }, { root, threshold: 0.15 });
    for (const card of cards) {
      card.classList.add("is-pending");
      observer.observe(card);
    }
    return () => {
      observer.disconnect();
      for (const card of cards) card.classList.remove("is-pending");
    };
  }, [key, hold]);
}

// Renders the final number; counting up from zero is decoration added on first sight.
export function CountUp({ value, format = String }: { value: number; format?: (value: number) => string }) {
  const ref = useRef<HTMLSpanElement>(null);
  useEffect(() => {
    const element = ref.current;
    if (!element || typeof IntersectionObserver === "undefined" || typeof requestAnimationFrame === "undefined" || prefersReducedMotion() || value <= 0) return;
    let frame = 0;
    const finish = () => { element.textContent = format(value); };
    const observer = new IntersectionObserver(entries => {
      if (!entries.some(entry => entry.isIntersecting)) return;
      observer.disconnect();
      const start = performance.now();
      const step = (now: number) => {
        const progress = Math.min(1, (now - start) / 600);
        if (progress >= 1) return finish();
        const eased = 1 - (1 - progress) ** 3;
        element.textContent = format(Number.isInteger(value) ? Math.round(value * eased) : Math.round(value * eased * 10) / 10);
        frame = requestAnimationFrame(step);
      };
      frame = requestAnimationFrame(step);
    });
    observer.observe(element);
    return () => {
      observer.disconnect();
      cancelAnimationFrame(frame);
      finish();
    };
  }, [value]);
  return <span ref={ref}>{format(value)}</span>;
}

export function StatCard({ label, value, detail, wide = false, index = 0, children }: {
  label: string;
  value?: ReactNode;
  detail?: ReactNode;
  wide?: boolean;
  index?: number;
  children?: ReactNode;
}) {
  return (
    <article className={`yir-card${wide ? " yir-card--wide" : ""}`} style={{ "--i": index % 4 } as CSSProperties}>
      <h3 className="yir-card__label">{label}</h3>
      {value !== undefined && <div className="yir-card__value">{value}</div>}
      {detail && <p className="yir-card__detail">{detail}</p>}
      {children}
    </article>
  );
}

// Horizontal bars for a ranked list (genres, themes, platforms). With `shelf`, each row opens its games.
export function ShareBars({ items, label, shelf }: { items: YearInReviewShare[]; label: string; shelf?: (name: string) => ShelfKey }) {
  return (
    <ul className="yir-bars" aria-label={label}>
      {items.map(item => <ShareBar key={item.name} item={item} shelf={shelf?.(item.name)} />)}
    </ul>
  );
}

function ShareBar({ item, shelf }: { item: YearInReviewShare; shelf?: ShelfKey }) {
  const body = (
    <>
      <span className="yir-bars__name">{item.name}</span>
      <span className="yir-bars__track"><span className="yir-bars__fill" style={{ width: percent(item.share) }} /></span>
      <span className="yir-bars__value">{percent(item.share)}</span>
    </>
  );
  return <li><ShelfRow shelf={shelf} className="yir-bars__row" ariaLabel={`${item.name}, ${percent(item.share)}: show its games`}>{body}</ShelfRow></li>;
}

// One bar split into segments, with a legend (platforms, solo vs together).
export function PercentBar({ segments, label }: { segments: Array<{ name: string; share: number }>; label: string }) {
  return (
    <div className="yir-split" aria-label={label}>
      <div className="yir-split__bar">
        {segments.map((segment, index) => <span key={segment.name} className={`yir-split__segment yir-split__segment--${index % 6}`} style={{ width: percent(segment.share) }} />)}
      </div>
      <ul className="yir-split__legend">
        {segments.map((segment, index) => (
          <li key={segment.name}><span className={`yir-split__swatch yir-split__segment--${index % 6}`} />{segment.name} <b>{percent(segment.share)}</b></li>
        ))}
      </ul>
    </div>
  );
}

// Vertical bars with a label under each (months, the rating spread). With `shelf`, each non-empty column opens its games.
export function ColumnChart({ values, labels, label, highlight, shelf, names = labels }: {
  values: number[];
  labels: string[];
  label: string;
  highlight?: number;
  shelf?: (index: number) => ShelfKey;
  // Spoken names for the columns when the labels are initials.
  names?: string[];
}) {
  const max = Math.max(1, ...values);
  return (
    <div className="yir-columns" role={shelf ? "group" : "img"} aria-label={label}>
      {values.map((value, index) => (
        <Column key={index} value={value} max={max} label={labels[index]} name={names[index]} highlight={index === highlight} index={index} shelf={shelf && value ? shelf(index) : undefined} />
      ))}
    </div>
  );
}

function Column({ value, max, label, name, highlight, index, shelf }: { value: number; max: number; label: string; name: string; highlight: boolean; index: number; shelf?: ShelfKey }) {
  const className = `yir-columns__column${highlight ? " is-highlight" : ""}`;
  const body = (
    <>
      <span className="yir-columns__count">{value || ""}</span>
      <span className="yir-columns__bar" style={{ height: `${(value / max) * 100}%`, "--n": index } as CSSProperties} />
      <span className="yir-columns__label">{label}</span>
    </>
  );
  return <ShelfRow shelf={shelf} className={className} ariaLabel={`${name}: ${plural(value, "game")}`}>{body}</ShelfRow>;
}

export function Cover({ game, size = "small" }: { game: Pick<YearInReviewGame, "coverImageId" | "title">; size?: "small" | "large" }) {
  return (
    <span className={`yir-cover yir-cover--${size}`}>
      {game.coverImageId
        ? <img src={igdbCoverSrc(game.coverImageId)} srcSet={igdbCoverSrcSet(game.coverImageId)} alt="" loading="lazy" draggable={false} />
        : <span className="yir-cover__none">{game.title.slice(0, 1)}</span>}
    </span>
  );
}

export function GameLine({ game, caption }: { game: YearInReviewGame; caption?: ReactNode }) {
  const body = (
    <>
      <Cover game={game} />
      <span className="yir-game__text">
        <b>{game.title}</b>
        <small>{caption ?? game.finishLabel}</small>
      </span>
    </>
  );
  return <OpenGameButton game={game} className="yir-game yir-game--open" fallbackClassName="yir-game">{body}</OpenGameButton>;
}

export function Footnotes({ notes }: { notes: Array<string | false | null | undefined> }) {
  const shown = notes.filter((note): note is string => Boolean(note));
  return shown.length ? <footer className="yir-footnotes">{shown.map(note => <p key={note}>{note}</p>)}</footer> : null;
}
