import type { CompletedGameFilters, CompletedGameListItem, CompletedViewMode } from "../../../../shared/types";
import type { CollectionWorkspace } from "../collectionWorkspace";
import { BulkActions, GenreField } from "./CollectionControls";
import type { CompletedGameGroup } from "../completedGroups";
import { Backdrop } from "../ui/Backdrop";
import { Button } from "../ui/Button";
import { Field, SelectShell } from "../ui/Field";
import { FramedPanel } from "../ui/FramedPanel";
import { igdbCoverGridSrcSet, igdbCoverSrc } from "../artwork";

const shortMonthFormatter = new Intl.DateTimeFormat("en-US", { month: "short", timeZone: "UTC" });

export function CompletedLibraryView({ wallpaperUrl, games, groups, viewMode, status, error, onViewMode, onDeleteSelected, onOpenDetail, onAddManual }: {
  wallpaperUrl?: string; games: CollectionWorkspace<CompletedGameListItem, CompletedGameFilters>; groups: CompletedGameGroup[];
  viewMode: CompletedViewMode; status: "starting" | "ready" | "error"; error?: string;
  onViewMode: (mode: CompletedViewMode) => void; onDeleteSelected: () => void;
  onOpenDetail: (item: CompletedGameListItem) => void; onAddManual: () => void;
}) {
  const { filters, setFilter: onFilter, debouncedSearch: onSearch, visibleItems: items, selectedIds: selectedCompletedIds, toggleSelection: onToggleSelection } = games;
  const firstCover = items.find(item => item.coverImageId)?.coverImageId;
  return <>
    <Backdrop src={wallpaperUrl || (firstCover ? igdbCoverSrc(firstCover) : undefined)} blur={18} />
    <FramedPanel className="completed-filters" as="aside">
      <h2>Filters</h2>
      <div className="completed-filters__fields">
        <Field label="Search"><input className="field__control" defaultValue={filters.search} onChange={event => onSearch(event.target.value)} placeholder="Title, developer, notes..." /></Field>
        <Field label="Platform"><input className="field__control" value={filters.platform ?? ""} onChange={event => onFilter("platform", event.target.value)} placeholder="Any" /></Field>
        <GenreField genre={games.genre} genres={games.genres} onGenre={games.setGenre} />
        <Field label="Year"><input className="field__control" value={filters.year ?? ""} onChange={event => onFilter("year", event.target.value)} placeholder="Any" /></Field>
        <Field label="Month"><input className="field__control" value={filters.month ?? ""} onChange={event => onFilter("month", event.target.value)} placeholder="YYYY-MM" /></Field>
        <Field label="Minimum rating"><input className="field__control" value={filters.rating ?? ""} onChange={event => onFilter("rating", event.target.value)} placeholder="Any" /></Field>
        <Field label="Date"><SelectShell><select className="field__control" value={filters.dateState ?? ""} onChange={event => onFilter("dateState", event.target.value as CompletedGameFilters["dateState"])}><option value="">All</option><option value="dated">Has date</option><option value="undated">Missing date</option></select></SelectShell></Field>
      </div>
      <div className="completed-filters__bottom"><div className="completed-view-toggle"><Button variant={viewMode === "grouped" ? "primary" : "outline"} onClick={() => onViewMode("grouped")}>Grouped</Button><Button variant={viewMode === "grid" ? "primary" : "outline"} onClick={() => onViewMode("grid")}>Grid</Button></div><Button onClick={onAddManual}>Add completed game</Button></div>
    </FramedPanel>
    <FramedPanel className="completed-library">
      <div className="completed-library__header"><h1>Completed Library</h1><span>{items.length} {items.length === 1 ? "game" : "games"}. Gold frames are rated 9 and above.</span></div>
      <BulkActions label="Bulk completed game actions" count={games.selectedVisibleCount} onSelectAll={games.selectAllVisible} onClear={games.clearSelection}><Button small danger onClick={onDeleteSelected}>Delete selected</Button></BulkActions>
      {status === "starting" && <div className="state">Loading completed library...</div>}
      {status === "error" && <div className="state error">Completed library unavailable: {error}</div>}
      {status === "ready" && items.length === 0 && <div className="state">No completed games yet. Add one with Add completed game.</div>}
      <div className="completed-library__scroll">
        {viewMode === "grid" ? <div className="completed-grid">{items.map(item => <Card key={item.id} item={item} selected={selectedCompletedIds.has(item.id)} onOpen={() => onOpenDetail(item)} onSelect={value => onToggleSelection(item.id, value)} />)}</div> : groups.map(group => <section key={group.key}><h2 className="completed-month"><span className="diamond">◆</span>{group.heading}</h2><div className="completed-grid">{group.items.map(item => <Card key={item.id} item={item} selected={selectedCompletedIds.has(item.id)} onOpen={() => onOpenDetail(item)} onSelect={value => onToggleSelection(item.id, value)} />)}</div></section>)}
      </div>
    </FramedPanel>
  </>;
}
function Card({ item, selected, onOpen, onSelect }: { item: CompletedGameListItem; selected: boolean; onOpen: () => void; onSelect: (value: boolean) => void }) {
  return <article className={`completed-card${item.ratingScore != null && item.ratingScore >= 9 ? " completed-card--gold" : ""}${selected ? " completed-card--selected" : ""}`} data-completed-game-id={item.id}>
    <label className="completed-card__check"><input className="check" aria-label={`Select ${item.title}`} type="checkbox" checked={selected} onChange={event => onSelect(event.target.checked)} /></label>
    <button type="button" className="completed-card__open" onClick={onOpen}>
      <div className="completed-card__art">{item.coverImageId ? <img src={igdbCoverSrc(item.coverImageId)} srcSet={igdbCoverGridSrcSet(item.coverImageId)} sizes="132px" alt="" loading="lazy" draggable={false} /> : <span>No cover</span>}</div>
      <div className="completed-card__title" title={item.title}>{item.title}</div>
      <div className="completed-card__meta">{item.ratingRaw && <span className="completed-card__rating">{item.ratingRaw}</span>}<span className="completed-card__date">{dateLabel(item)}</span></div>
      {item.matchStatus === "needsReview" && <div className="completed-card__flag warning">match needs review</div>}
    </button>
  </article>;
}
function dateLabel(item: CompletedGameListItem) {
  if (item.completionDate) { const [y, m, d] = item.completionDate.split("-").map(Number); if (y && m && d) return `finished ${d} ${shortMonthFormatter.format(new Date(Date.UTC(y, m - 1, d)))}`; }
  if (item.completionMonth) { const [y, m] = item.completionMonth.split("-").map(Number); if (y && m) return `finished ${shortMonthFormatter.format(new Date(Date.UTC(y, m - 1, 1)))} ${y}`; }
  return item.completionYear ? `finished ${item.completionYear}` : "date missing";
}
