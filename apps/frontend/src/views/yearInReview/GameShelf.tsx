import { useEffect, useRef, type CSSProperties, type ReactNode } from "react";
import type { YearInReviewGame, YearInReviewShare, YearInReviewSummary } from "../../../../../shared/types";
import { wholeRating } from "../../../../../shared/wholeRating";
import { Cover, formatRating, MONTH_NAMES, OpenGameButton, plural, useShelfButton, type ShelfKey } from "./parts";

// A shelf is the games behind one category on a card: a month bar, a genre, a platform, a rating, the day-one
// list. Clicking the category unrolls its shelf under the chapter's cards. The key is a plain string so the
// place to come back to (after opening a game) can hold it:
//   "day-one" · "nine" · "month:<1-12>" · "rating:<0-10>" · "genre:<name>" · "theme:<name>" · "platform:<name>"

interface Shelf {
  title: string;
  detail: string;
  games: YearInReviewGame[];
}

// Same bar as the overview's "rated 9 or higher" count.
const NINE_OR_HIGHER = 9;

export function resolveShelf(summary: YearInReviewSummary, key: string | null | undefined): Shelf | null {
  if (!key) return null;
  const at = key.indexOf(":");
  const kind = at < 0 ? key : key.slice(0, at);
  const value = at < 0 ? "" : key.slice(at + 1);
  const byIds = (share: YearInReviewShare | undefined) => {
    const ids = new Set(share?.ids ?? []);
    return summary.games.filter(game => ids.has(game.id));
  };
  switch (kind) {
    case "day-one":
      return summary.timing.dayOne ? { title: "Day-one finishes", detail: "Finished within a month of release", games: summary.timing.dayOne.games } : null;
    case "nine":
      return { title: `Rated ${NINE_OR_HIGHER} or higher`, detail: "Your best of the year", games: summary.games.filter(game => game.ratingScore !== null && game.ratingScore >= NINE_OR_HIGHER) };
    case "month": {
      const month = Number(value);
      return month >= 1 && month <= 12 ? { title: `Finished in ${MONTH_NAMES[month - 1]}`, detail: "By finish month", games: summary.games.filter(game => game.month === month) } : null;
    }
    case "rating": {
      const rating = Number(value);
      return value !== "" && rating >= 0 && rating <= 10 ? { title: `Rated ${rating}`, detail: "Rounded to a whole rating", games: summary.games.filter(game => game.ratingScore !== null && wholeRating(game.ratingScore) === rating) } : null;
    }
    case "genre":
      return { title: value, detail: "Genre", games: byIds(summary.taste.genres.find(share => share.name === value)) };
    case "theme":
      return { title: value, detail: "Theme", games: byIds(summary.taste.themes.find(share => share.name === value)) };
    case "platform":
      return { title: `Played on ${value}`, detail: "Platform", games: byIds(summary.taste.platforms.find(share => share.name === value)) };
    default:
      return null;
  }
}

// A card's "Show" row for its whole list.
export function ShowShelf({ shelf, children }: { shelf: ShelfKey; children: ReactNode }) {
  const props = useShelfButton(shelf);
  if (!props) return null;
  return <button {...props} className="yir-show"><span>{children}</span><span className="yir-show__hint">Show ›</span></button>;
}

// The unrolled shelf under the cards.
export function ShelfReveal({ shelf, onClose, scrollIntoView }: { shelf: Shelf; onClose: () => void; scrollIntoView: boolean }) {
  const section = useRef<HTMLElement>(null);
  useEffect(() => {
    if (scrollIntoView) section.current?.scrollIntoView?.({ behavior: "smooth", block: "nearest" });
  }, [shelf.title, scrollIntoView]);
  return (
    <section className="yir-reveal" aria-label={shelf.title} ref={section}>
      <header className="yir-reveal__head">
        <h3 className="yir-reveal__title">{shelf.title}</h3>
        <span className="yir-card__detail">{shelf.detail} · {plural(shelf.games.length, "game")}</span>
        <button type="button" className="yir-reveal__close" onClick={onClose}>Close</button>
      </header>
      {shelf.games.length ? <GameTiles games={shelf.games} /> : <p className="yir-card__detail">No games here.</p>}
    </section>
  );
}

export function GameTiles({ games, large = false, label }: { games: YearInReviewGame[]; large?: boolean; label?: string }) {
  return (
    <ol className={`yir-tiles${large ? " yir-tiles--large" : ""}`} aria-label={label}>
      {games.map((game, index) => <GameTile key={game.id} game={game} index={index} />)}
    </ol>
  );
}

// A cover with its rating, and the title and (platform) under it. Opens the game's page when the stage allows it.
function GameTile({ game, index }: { game: YearInReviewGame; index: number }) {
  const art = (
    <span className="yir-tile__art">
      <Cover game={game} />
      {game.ratingScore !== null && <span className="yir-tile__score">{formatRating(game.ratingScore)}</span>}
    </span>
  );
  return (
    <li className="yir-tile" style={{ "--n": Math.min(index, 20) } as CSSProperties} title={`${game.title} · ${game.finishLabel}`}>
      <OpenGameButton game={game} className="yir-tile__open">{art}</OpenGameButton>
      <span className="yir-tile__caption">{game.title}{game.userPlatform && <small> ({game.userPlatform})</small>}</span>
    </li>
  );
}
