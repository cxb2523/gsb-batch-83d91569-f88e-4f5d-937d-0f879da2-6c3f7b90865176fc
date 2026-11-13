import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";
import type { ReleaseListItem, SyncStatus } from "../../../../shared/types";
import type { ReleaseDeletionMode } from "../releaseDeletion";
import { artworkSrc } from "../artwork";
import { Backdrop } from "../ui/Backdrop";
import { Button } from "../ui/Button";
import { WatchButton } from "../ui/WatchButton";
import { listDateBadge } from "../ui/dateChange";
import { Field, SelectShell } from "../ui/Field";
import { FramedPanel } from "../ui/FramedPanel";
import { bannerLabel, daysUntil, rowSubLine, rowWhenLabel, stripCurrentYear } from "../ui/countdown";
import type { CollectionWorkspace } from "../collectionWorkspace";
import type { ReleaseFilters } from "../releaseWorkspace";
import { BulkActions, GenreField, SyncState } from "./CollectionControls";
import type { DemoWorkflow } from "../useDemoWorkflow";

interface ReleaseGroup { heading: string; items: ReleaseListItem[] }
export function UpcomingView({ apiBaseUrl, wallpaperUrl, releases, groups, status, syncStatus, error, onDeleteSelected, onOpenDetail, onSetWatched, onAddGame, demo, onSetUpOwnLibrary }: {
  apiBaseUrl: string; wallpaperUrl?: string; releases: CollectionWorkspace<ReleaseListItem, ReleaseFilters>; groups: ReleaseGroup[];
  status: "starting" | "ready" | "error"; syncStatus: SyncStatus; error?: string;
  onDeleteSelected: (mode: ReleaseDeletionMode) => void; onOpenDetail: (item: ReleaseListItem) => void; onSetWatched: (item: ReleaseListItem, watched: boolean) => void; onAddGame: () => void;
  demo: DemoWorkflow; onSetUpOwnLibrary: () => void;
}) {
  const { filters, setFilter: onFilter, debouncedSearch: onSearch, selectedIds: selectedReleaseIds, toggleSelection: onToggleReleaseSelection } = releases;
  // An empty list under a filter means no match, not an empty library.
  const filtering = Boolean(filters.search || filters.publisher || filters.category || filters.platform || filters.datePrecision || filters.watchedOnly || releases.genre);
  const showWelcome = status === "ready" && releases.loadedCount === 0 && !filtering && !demo.loaded;
  const { includeReleased, includeHidden, watchedOnly } = filters;
  const [moreFilters, setMoreFilters] = useState(false);
  const [featuredId, setFeaturedId] = useState<string | null>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const today = new Date();
  const items = useMemo(() => groups.flatMap(group => group.items), [groups]);
  const featured = items.find(item => item.id === featuredId) ?? items.find(item => item.datePrecision !== "Exact" || (item.releaseDate && daysUntil(item.releaseDate, today) >= 0)) ?? items[0];
  useEffect(() => { if (featured?.id !== featuredId) setFeaturedId(featured?.id ?? null); }, [featured?.id, featuredId]);
  const featuredBadge = listDateBadge(featured?.lastDateChange);
  const art = featured?.artworks ?? [];
  const backdropArt = art.find(a => a.source === "artwork") ?? art.find(a => a.source === "local" || a.source === "steamgriddb");
  const cover = art.find(a => a.source === "cover") ?? art[0];
  const backdropSrc = backdropArt ? artworkSrc(backdropArt, "detail", apiBaseUrl) : wallpaperUrl || (cover ? artworkSrc(cover, "backdrop", apiBaseUrl) : undefined);
  const backdropFillSrc = backdropArt ? artworkSrc(backdropArt, "backdrop", apiBaseUrl) : undefined;
  const backdropBlur: 0 | 18 = backdropArt || wallpaperUrl || !cover ? 0 : 18;
  const activeFilterCount = [filters.publisher, filters.category, filters.platform, filters.datePrecision, includeReleased, includeHidden, watchedOnly].filter(Boolean).length;
  const handleListKey = (event: KeyboardEvent<HTMLDivElement>) => {
    if (!items.length || !["ArrowUp", "ArrowDown", "Enter"].includes(event.key)) return;
    if ((event.target as HTMLElement).closest("input,select")) return;
    if (event.key === "Enter") { if (featured) onOpenDetail(featured); return; }
    event.preventDefault();
    const index = Math.max(0, items.findIndex(item => item.id === featured?.id));
    const next = items[Math.max(0, Math.min(items.length - 1, index + (event.key === "ArrowDown" ? 1 : -1)))];
    setFeaturedId(next.id);
    listRef.current?.querySelector<HTMLElement>(`[data-release-id="${CSS.escape(next.id)}"]`)?.scrollIntoView({ block: "nearest" });
  };
  return <>
    <Backdrop src={backdropSrc} fillSrc={backdropFillSrc} blur={backdropBlur} fit="art" />
    {featured && <div className="upcoming-banner"><span className="upcoming-banner__line" /><span>{bannerLabel(featured, today)}</span><span className="upcoming-banner__line" /></div>}
    <FramedPanel className="upcoming-list" as="aside">
      <div className="upcoming-list__header"><h1>Upcoming</h1><Button small onClick={onAddGame}>Add game</Button></div>
      <Field label="Search"><input className="field__control" defaultValue={filters.search} onChange={event => onSearch(event.target.value)} placeholder="Title, publisher, DLC..." /></Field>
      <GenreField genre={releases.genre} genres={releases.genres} onGenre={releases.setGenre} />
      <button type="button" className="more-filters" aria-expanded={moreFilters} onClick={() => setMoreFilters(value => !value)}>More filters{activeFilterCount ? ` (${activeFilterCount})` : ""}</button>
      {moreFilters && <div className="upcoming-extra-filters" aria-label="Release filters">
        <Field label="Publisher"><input className="field__control" value={filters.publisher} onChange={event => onFilter("publisher", event.target.value)} placeholder="Any" /></Field>
        <Field label="Category"><SelectShell><select className="field__control" value={filters.category} onChange={event => onFilter("category", event.target.value)}><option value="">All</option><option>Main</option><option>DLC</option><option>Expansion</option><option>Remake</option><option>Remaster</option><option>Port</option></select></SelectShell></Field>
        <Field label="Platform"><input className="field__control" value={filters.platform} onChange={event => onFilter("platform", event.target.value)} placeholder="Any" /></Field>
        <Field label="Precision"><SelectShell><select className="field__control" value={filters.datePrecision} onChange={event => onFilter("datePrecision", event.target.value)}><option value="">All</option><option>Exact</option><option>Month</option><option>Window</option><option>Year</option></select></SelectShell></Field>
        <div className="upcoming-extra-filters__checks"><label><input className="check" type="checkbox" checked={includeReleased} onChange={event => onFilter("includeReleased", event.target.checked)} /> Released</label><label><input className="check" type="checkbox" checked={includeHidden} onChange={event => onFilter("includeHidden", event.target.checked)} /> Hidden</label><label><input className="check" type="checkbox" checked={watchedOnly} onChange={event => onFilter("watchedOnly", event.target.checked)} /> Watched only</label></div>
      </div>}
      <BulkActions label="Bulk release actions" count={releases.selectedVisibleCount} onSelectAll={releases.selectAllVisible} onClear={releases.clearSelection}><Button small danger onClick={() => onDeleteSelected("delete")}>Delete selected</Button><Button small danger onClick={() => onDeleteSelected("delete-block")}>Delete + block selected</Button></BulkActions>
      <SyncState status={syncStatus.status} message={syncStatus.message} />
      {status === "starting" && <div className="state">Backend starting...</div>}
      {status === "error" && <div className="state error">Backend unavailable: {error}</div>}
      {demo.loaded && <div className="sample-banner">You're looking at the sample library. <Button small onClick={() => void demo.actions.remove()}>Remove sample data</Button></div>}
      {showWelcome && <Welcome onTrySample={() => void demo.actions.load()} onSetUp={onSetUpOwnLibrary} />}
      {status === "ready" && (releases.loadedCount > 0 || filtering) && releases.visibleItems.length === 0 && <div className="state">No releases match this filter.</div>}
      <div className="upcoming-list__scroll" ref={listRef} onKeyDown={handleListKey} tabIndex={0}>
        {groups.map(group => <section key={group.heading}><h2 className="upcoming-month">{stripCurrentYear(group.heading, today)}</h2>{group.items.map(item => {
          const rowCover = item.artworks.find(a => a.source === "cover") ?? item.artworks[0];
          const badge = listDateBadge(item.lastDateChange);
          return <div className={`release-row${featured?.id === item.id ? " release-row--selected" : ""}`} data-release-id={item.id} key={item.id}>
            <span className="release-row__marker">{featured?.id === item.id ? "◆" : ""}</span>
            <label className="release-row__check"><input className="check" aria-label={`Select ${item.title}`} type="checkbox" checked={selectedReleaseIds.has(item.id)} onChange={event => onToggleReleaseSelection(item.id, event.target.checked)} /></label>
            <button type="button" className="release-row__open" onClick={() => setFeaturedId(item.id)} onDoubleClick={() => onOpenDetail(item)} onKeyDown={event => { if (event.key === "Enter") { event.stopPropagation(); onOpenDetail(item); } }}>
              <span className="release-row__cover">{rowCover && <img src={artworkSrc(rowCover, "small", apiBaseUrl)} alt="" loading="lazy" draggable={false} />}</span>
              <span className="release-row__text"><strong>{item.watched && <span className="watch-star" title="Watching">★ </span>}{item.title}</strong><small>{rowSubLine(item)}</small>{badge && <small className={`date-badge date-badge--${badge.kind}`}>{badge.label}</small>}</span>
              <span className="release-row__when">{rowWhenLabel(item, today)}</span>
            </button>
          </div>;
        })}</section>)}
      </div>
    </FramedPanel>
    {showWelcome && <WelcomeTour />}
    {featured && <FramedPanel className="upcoming-feature"><div className="upcoming-feature__layout"><div className="upcoming-feature__cover">{cover && <img src={artworkSrc(cover, "grid", apiBaseUrl)} alt="" draggable={false} />}</div><div className="upcoming-feature__content"><h2>{featured.title}</h2>{featuredBadge && <p className={`date-badge date-badge--${featuredBadge.kind}`}>{featuredBadge.label}</p>}<p>{[featured.publishers[0] ?? featured.developers[0], featured.category === "Main" ? "" : featured.category, featured.platforms.join(", ")].filter(Boolean).join(". ")}.</p><div className="upcoming-feature__actions"><Button variant="primary" onClick={() => onOpenDetail(featured)}>Open details</Button><WatchButton watched={Boolean(featured.watched)} onChange={watched => onSetWatched(featured, watched)} /></div></div></div></FramedPanel>}
  </>;
}

// Beside the welcome: what each screen does, so a first-time user sees the app before choosing.
const TOUR = [
  ["Upcoming", "The games coming from the publishers you follow, with a countdown, artwork and trailers."],
  ["Completed Library", "A journal of the games you finish: when, on what, your rating and notes."],
  ["Year in Review", "Your year of games told in five illustrated chapters, ready to save as an image."],
  ["Randomizer", "Can't decide what to play? Spin for a released game that fits your filters."]
] as const;

function WelcomeTour() {
  return (
    <FramedPanel className="welcome-tour" aria-label="What you can do">
      <h2>What you can do</h2>
      <ul className="welcome-tour__list">{TOUR.map(([title, text]) => <li key={title}><strong>{title}</strong><span>{text}</span></li>)}</ul>
      <p className="welcome-tour__privacy">Everything stays on this computer. No account, no analytics.</p>
    </FramedPanel>
  );
}

// A new, empty library: try the app with sample data, or set it up with your own IGDB keys and publishers.
function Welcome({ onTrySample, onSetUp }: { onTrySample: () => void; onSetUp: () => void }) {
  return (
    <div className="welcome">
      <h2>Welcome to Game Release Tracker</h2>
      <p>Track upcoming releases from the publishers you follow, keep a journal of the games you finish, and get a yearly recap.</p>
      <div className="welcome__choices">
        <div>
          <Button variant="primary" onClick={onTrySample}>Try it with sample data</Button>
          <p>Loads 30 upcoming games, a finished-games library with its Year in Review, and 267 games for the Randomizer, no account needed. You can remove it any time.</p>
        </div>
        <div>
          <Button variant="outline" onClick={onSetUp}>Set up my own</Button>
          <p>Add your free IGDB keys, choose the publishers to follow, then press Sync now.</p>
        </div>
      </div>
    </div>
  );
}
