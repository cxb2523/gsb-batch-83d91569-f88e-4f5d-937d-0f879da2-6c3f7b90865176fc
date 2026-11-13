import { useEffect, useLayoutEffect, useRef, useState, type CSSProperties, type FormEvent } from "react";
import type {
  RandomizerFilters,
  RandomizerGameOption,
  RandomizerHistoryItem,
  RandomizerOption,
  RandomizerPlatformFamily,
  RandomizerPlatformOption,
  RandomizerPick,
  RandomizerPreset,
  RandomizerSeriesOption,
  RandomizerSpinResponse
} from "../../../../shared/types";
import { igdbCoverSrc } from "../artwork";
import { canAnimate } from "../motion";
import { Backdrop } from "../ui/Backdrop";
import { Button } from "../ui/Button";
import { Field, SelectShell } from "../ui/Field";
import { FramedPanel } from "../ui/FramedPanel";
import type { RandomizerWorkflow } from "../useRandomizerWorkflow";
import { addIds, labelKey, removeIds, seriesKey, setFlag, setNumber, setOption, setSimilarTo, toggleGroup, toggleId, togglePreset, type IdListKey, type NumberKey } from "../randomizerFilters";

type IdFilterKey = Extract<IdListKey, "genreIds" | "excludeGenreIds" | "themeIds" | "excludeThemeIds" | "gameModeIds" | "perspectiveIds">;
type OptionFilterKey = IdFilterKey | Extract<IdListKey, "tagIds" | "excludeTagIds">;
type FiltersUpdate = (update: (current: RandomizerFilters) => RandomizerFilters) => void;

export function RandomizerView({ workflow, wallpaperUrl, onOpenSettings }: {
  workflow: RandomizerWorkflow;
  wallpaperUrl?: string;
  onOpenSettings: () => void;
}) {
  const { filters, options, optionsStatus, missingCredentials, phase, result, reel, history, labels, actions } = workflow;
  const { setFilters, searchSeries, searchGames, rememberLabel, moreLikeThis, resetFilters, clearHistory } = actions;
  const spin = () => { void actions.spin(); };
  const tagSearch: OptionSearch = {
    prompt: "Popular tags...",
    placeholder: "Search any tag",
    onSearch: actions.searchTags,
    rememberedName: id => labels[labelKey("tag", id)],
    onPick: option => rememberLabel(labelKey("tag", option.id), option.name)
  };
  const spinning = phase === "spinning";
  // When a spin lands, the reel slows down and stops on the pick before the card appears.
  const [landing, setLanding] = useState(false);
  const [landed, setLanded] = useState(false);
  const previousPhase = useRef(phase);
  useEffect(() => {
    const was = previousPhase.current;
    previousPhase.current = phase;
    if (phase === "spinning") setLanded(false);
    if (was === "spinning" && phase === "ready" && result?.pick && canAnimate()) setLanding(true);
  }, [phase]);
  const busy = spinning || landing;
  return (
    <>
      <Backdrop src={wallpaperUrl} blur={18} />
      <FramedPanel as="aside" className="randomizer-filters" aria-label="Randomizer filters">
        <h2>Filters</h2>
        <div className="randomizer-filters__scroll">
          {optionsStatus === "loading" && <div className="state">Loading IGDB filter lists...</div>}
          <QuickPicks filters={filters} onChange={setFilters} />
          <SimilarPicker filters={filters} onChange={setFilters} onSearch={searchGames} />
          <SeriesPicker labels={labels} filters={filters} onChange={setFilters} onSearch={searchSeries} onRemember={rememberLabel} />
          <PlatformPicker list={options?.platforms} filters={filters} onChange={setFilters} />
          <OptionPicker label="Genres" hint="any of" filterKey="genreIds" list={options?.genres} filters={filters} onChange={setFilters} />
          <OptionPicker label="Exclude genres" filterKey="excludeGenreIds" list={options?.genres} filters={filters} onChange={setFilters} />
          <OptionPicker label="Themes" hint="any of" filterKey="themeIds" list={options?.themes} filters={filters} onChange={setFilters} />
          <OptionPicker label="Exclude themes" filterKey="excludeThemeIds" list={options?.themes} filters={filters} onChange={setFilters} />
          <OptionPicker label="Tags" hint="all of" filterKey="tagIds" list={options?.tags} filters={filters} onChange={setFilters} search={tagSearch} />
          <OptionPicker label="Exclude tags" filterKey="excludeTagIds" list={options?.tags} filters={filters} onChange={setFilters} search={tagSearch} />
          <OptionPicker label="Game modes" hint="any of" filterKey="gameModeIds" list={options?.gameModes} filters={filters} onChange={setFilters} />
          <OptionPicker label="Camera view" hint="any of" filterKey="perspectiveIds" list={options?.perspectives} filters={filters} onChange={setFilters} />
          <div className="randomizer-filters__pair">
            <NumberField label="Min rating" filterKey="minRating" min={0} max={100} placeholder="0" filters={filters} onChange={setFilters} />
            <NumberField label="Max rating" filterKey="maxRating" min={0} max={100} placeholder="100" filters={filters} onChange={setFilters} />
          </div>
          <div className="randomizer-filters__pair">
            <NumberField label="Min ratings count" filterKey="minRatingCount" min={0} placeholder="5" filters={filters} onChange={setFilters} />
            <NumberField label="Max ratings count" filterKey="maxRatingCount" min={0} placeholder="Any" filters={filters} onChange={setFilters} />
          </div>
          <div className="randomizer-filters__pair">
            <NumberField label="Released from" filterKey="releasedFromYear" min={1950} max={2100} placeholder="Year" filters={filters} onChange={setFilters} />
            <NumberField label="Released to" filterKey="releasedToYear" min={1950} max={2100} placeholder="Year" filters={filters} onChange={setFilters} />
          </div>
          <div className="randomizer-filters__checks">
            <Check label="Include unrated games (many are obscure; pair with other filters)" checked={Boolean(filters.includeUnrated)} onChange={value => setFilters(current => setFlag(current, "includeUnrated", value))} />
            <Check label="Include remakes, remasters and ports" checked={filters.includeRemakes !== false} onChange={value => setFilters(current => setOption(current, "includeRemakes", value))} />
            <Check label="Hide games in my Completed Library" checked={filters.hideCompleted !== false} onChange={value => setFilters(current => setOption(current, "hideCompleted", value))} />
            <Check label="Hide games in Upcoming" checked={Boolean(filters.hideUpcoming)} onChange={value => setFilters(current => setOption(current, "hideUpcoming", value))} />
          </div>
        </div>
        <div className="randomizer-filters__bottom">
          <Button small onClick={resetFilters}>Reset filters</Button>
        </div>
      </FramedPanel>

      <FramedPanel className="randomizer-stage">
        <div className="randomizer-stage__header">
          <div>
            <p className="kicker">Something to play</p>
            <h1>Randomizer</h1>
          </div>
          <Button variant="primary" className="randomizer-spin" onClick={spin} disabled={busy || missingCredentials}>
            {busy ? "Spinning..." : result?.pick ? "Spin again" : "Spin"}
          </Button>
        </div>

        <div className="randomizer-stage__body" aria-live="polite">
          {missingCredentials ? (
            <div className="randomizer-empty">
              <p>IGDB credentials are required for the randomizer.</p>
              <Button small onClick={onOpenSettings}>Open Settings</Button>
            </div>
          ) : spinning ? (
            <Reel items={reel} />
          ) : landing && result?.pick ? (
            <ReelLanding items={reel} onDone={() => { setLanding(false); setLanded(true); }} />
          ) : result?.pick ? (
            <PickCard result={result} onMoreLikeThis={moreLikeThis} landed={landed} />
          ) : result ? (
            <div className="randomizer-empty"><p>{result.reason ?? "Nothing matches these filters."}</p></div>
          ) : (
            <div className="randomizer-empty"><p>{options?.sample
              ? "Sample mode: spins pick from 267 games of the sample library. Add your IGDB keys in Settings to spin from all of IGDB and use tags, series and similar games."
              : "Set filters if you like, then press Spin for a random game from IGDB."}</p></div>
          )}
        </div>

        <RecentPicks history={history} onClear={clearHistory} />
      </FramedPanel>
    </>
  );
}

const presetLabels: Array<[RandomizerPreset, string]> = [["jrpg", "JRPG"], ["anime", "Anime"]];

// One-click toggles for the Japanese-game filters people reach for most.
function QuickPicks({ filters, onChange }: { filters: RandomizerFilters; onChange: FiltersUpdate }) {
  const presets = filters.presets ?? [];
  return (
    <Field label="Quick picks" className="randomizer-picker">
      <span className="randomizer-chips">
        {presetLabels.map(([preset, label]) => (
          <Toggle key={preset} label={label} pressed={presets.includes(preset)} onClick={() => onChange(current => togglePreset(current, preset))} />
        ))}
        <Toggle label="Made in Japan" pressed={Boolean(filters.madeInJapan)} onClick={() => onChange(current => setFlag(current, "madeInJapan", !current.madeInJapan))} />
      </span>
    </Field>
  );
}

function Toggle({ label, pressed, onClick }: { label: string; pressed: boolean; onClick: () => void }) {
  return (
    <button type="button" className={`randomizer-chip randomizer-toggle${pressed ? " active" : ""}`} aria-pressed={pressed} onClick={onClick}>{label}</button>
  );
}

const platformFamilies: RandomizerPlatformFamily[] = ["PlayStation", "Xbox", "Nintendo", "PC"];

// Grouped by family. Nothing selected means every listed platform.
function PlatformPicker({ list, filters, onChange }: { list: RandomizerPlatformOption[] | undefined; filters: RandomizerFilters; onChange: FiltersUpdate }) {
  const selected = filters.platformIds ?? [];
  return (
    <Field label="Platforms (any of, none = all)" className="randomizer-picker">
      {!list && <span className="state">Unavailable</span>}
      {platformFamilies.map(family => {
        const members = (list ?? []).filter(platform => platform.family === family);
        if (!members.length) return null;
        const ids = members.map(platform => platform.id);
        const allOn = ids.every(id => selected.includes(id));
        return (
          <div className="randomizer-family" key={family} role="group" aria-label={family}>
            {members.length > 1 && (
              <Toggle
                label={`All ${family}`}
                pressed={allOn}
                onClick={() => onChange(current => toggleGroup(current, "platformIds", ids))}
              />
            )}
            {members.map(platform => <Toggle key={platform.id} label={platform.name} pressed={selected.includes(platform.id)} onClick={() => onChange(current => toggleId(current, "platformIds", platform.id))} />)}
          </div>
        );
      })}
    </Field>
  );
}

// A name search against IGDB: type, press Find, click a result to add it.
function SearchBox<T extends RandomizerOption>({ label, placeholder, onSearch, onPick, hideIds = [], describe = item => item.name }: {
  label: string;
  placeholder: string;
  onSearch: (text: string) => Promise<T[]>;
  onPick: (item: T) => void;
  hideIds?: number[];
  describe?: (item: T) => string;
}) {
  const [text, setText] = useState("");
  const [results, setResults] = useState<T[] | null>(null);
  const [state, setState] = useState<"idle" | "searching" | "error">("idle");
  const search = async (event: FormEvent) => {
    event.preventDefault();
    if (text.trim().length < 2) return;
    setState("searching");
    try {
      setResults(await onSearch(text.trim()));
      setState("idle");
    } catch {
      setResults(null);
      setState("error");
    }
  };
  const shown = results?.filter(item => !hideIds.includes(item.id)) ?? null;
  return (
    <>
      <form className="randomizer-tag-search" onSubmit={search}>
        <input className="field__control" type="search" aria-label={`Search ${label.toLowerCase()}`} placeholder={placeholder} value={text} onChange={event => setText(event.target.value)} />
        <Button small type="submit" disabled={state === "searching" || text.trim().length < 2}>Find</Button>
      </form>
      {state === "searching" && <span className="state">Searching IGDB...</span>}
      {state === "error" && <span className="state warning">Search failed. Try again.</span>}
      {shown && state === "idle" && (
        shown.length ? (
          <span className="randomizer-chips" aria-label={`${label} search results`}>
            {shown.map(item => (
              <button type="button" key={item.id} className="randomizer-chip randomizer-chip--add" onClick={() => onPick(item)}>+ {describe(item)}</button>
            ))}
          </span>
        ) : <span className="state">Nothing matches.</span>
      )}
    </>
  );
}

function RemovableChips({ items, onRemove }: { items: Array<{ key: string; name: string }>; onRemove: (key: string) => void }) {
  if (!items.length) return null;
  return (
    <span className="randomizer-chips">
      {items.map(item => (
        <button type="button" key={item.key} className="randomizer-chip" aria-label={`Remove ${item.name}`} onClick={() => onRemove(item.key)}>
          {item.name} <span aria-hidden="true">×</span>
        </button>
      ))}
    </span>
  );
}

// Franchises and collections by name; a game in any chosen one matches.
function SeriesPicker({ labels, filters, onChange, onSearch, onRemember }: {
  labels: Record<string, string>;
  filters: RandomizerFilters;
  onChange: FiltersUpdate;
  onSearch?: (text: string) => Promise<RandomizerSeriesOption[]>;
  onRemember?: (key: string, name: string) => void;
}) {
  const chosen = [
    ...(filters.franchiseIds ?? []).map(id => ({ key: labelKey("franchise", id), kind: "franchise" as const, id })),
    ...(filters.collectionIds ?? []).map(id => ({ key: labelKey("collection", id), kind: "collection" as const, id }))
  ];
  const add = (series: RandomizerSeriesOption) => {
    onRemember?.(labelKey(series.kind, series.id), series.name);
    onChange(current => addIds(current, seriesKey(series.kind), [series.id]));
  };
  const remove = (chipKey: string) => {
    const item = chosen.find(entry => entry.key === chipKey);
    if (item) onChange(current => removeIds(current, seriesKey(item.kind), [item.id]));
  };
  if (!onSearch && !chosen.length) return null;
  return (
    <Field label="Series (any of)" className="randomizer-picker">
      {onSearch && (
        <SearchBox
          label="Series"
          placeholder="Final Fantasy, Persona..."
          onSearch={onSearch}
          onPick={add}
          describe={series => `${series.name} · ${series.kind === "franchise" ? "franchise" : "series"}`}
        />
      )}
      <RemovableChips items={chosen.map(item => ({ key: item.key, name: labels[item.key] ?? `#${item.id}` }))} onRemove={remove} />
    </Field>
  );
}

// Spin only games IGDB lists as similar to one game.
function SimilarPicker({ filters, onChange, onSearch }: {
  filters: RandomizerFilters;
  onChange: FiltersUpdate;
  onSearch?: (text: string) => Promise<RandomizerGameOption[]>;
}) {
  const clear = () => onChange(current => setSimilarTo(current, null));
  if (!onSearch && !filters.similarToId) return null;
  return (
    <Field label="Similar to" className="randomizer-picker">
      {filters.similarToId ? (
        <RemovableChips items={[{ key: "seed", name: filters.similarToTitle ?? `#${filters.similarToId}` }]} onRemove={clear} />
      ) : onSearch && (
        <SearchBox
          label="Similar to"
          placeholder="Search a game"
          onSearch={onSearch}
          onPick={game => onChange(current => setSimilarTo(current, game))}
          describe={game => (game.year ? `${game.name} (${game.year})` : game.name)}
        />
      )}
    </Field>
  );
}

// Search lets a picker add options beyond the popular list and remember their names.
interface OptionSearch {
  prompt: string;
  placeholder: string;
  onSearch: (text: string) => Promise<RandomizerOption[]>;
  rememberedName: (id: number) => string | undefined;
  onPick: (option: RandomizerOption) => void;
}

function OptionPicker({ label, hint, filterKey, list, filters, onChange, search }: {
  label: string;
  hint?: string;
  filterKey: OptionFilterKey;
  list: RandomizerOption[] | undefined;
  filters: RandomizerFilters;
  onChange: FiltersUpdate;
  search?: OptionSearch;
}) {
  const selected = filters[filterKey] ?? [];
  const nameOf = (id: number) => list?.find(option => option.id === id)?.name ?? search?.rememberedName(id) ?? `#${id}`;
  const add = (option: RandomizerOption) => {
    search?.onPick(option);
    onChange(current => addIds(current, filterKey, [option.id]));
  };
  const available = (list ?? []).filter(option => !selected.includes(option.id));
  return (
    <Field label={hint ? `${label} (${hint})` : label} className="randomizer-picker">
      <SelectShell>
        <select
          className="field__control"
          aria-label={`Add ${label.toLowerCase()}`}
          value=""
          disabled={!list}
          onChange={event => {
            const option = list?.find(item => item.id === Number(event.target.value));
            if (option) add(option);
          }}
        >
          <option value="">{list ? (search?.prompt ?? `Add ${label.toLowerCase()}...`) : "Unavailable"}</option>
          {available.map(option => <option key={option.id} value={option.id}>{option.name}</option>)}
        </select>
      </SelectShell>
      {search && <SearchBox label={label} placeholder={search.placeholder} onSearch={search.onSearch} onPick={add} hideIds={selected} />}
      <RemovableChips items={selected.map(id => ({ key: String(id), name: nameOf(id) }))} onRemove={key => onChange(current => removeIds(current, filterKey, [Number(key)]))} />
    </Field>
  );
}

function NumberField({ label, filterKey, min, max, placeholder, filters, onChange }: {
  label: string;
  filterKey: NumberKey;
  min?: number;
  max?: number;
  placeholder?: string;
  filters: RandomizerFilters;
  onChange: FiltersUpdate;
}) {
  const value = filters[filterKey];
  return (
    <Field label={label}>
      <input
        className="field__control"
        type="number"
        inputMode="numeric"
        min={min}
        max={max}
        placeholder={placeholder}
        value={value ?? ""}
        onChange={event => {
          const text = event.target.value;
          onChange(current => setNumber(current, filterKey, text));
        }}
      />
    </Field>
  );
}

function Check({ label, checked, onChange }: { label: string; checked: boolean; onChange: (value: boolean) => void }) {
  return <label><input type="checkbox" className="check" checked={checked} onChange={event => onChange(event.target.checked)} /> {label}</label>;
}

function Reel({ items }: { items: RandomizerSpinResponse["reels"] }) {
  const tiles = items.length ? items : Array.from({ length: 6 }, () => ({ title: "", coverImageId: null }));
  // Doubled so the strip loops seamlessly.
  return (
    <div className="randomizer-reel" aria-label="Spinning">
      <div className="randomizer-reel__strip">
        {[...tiles, ...tiles].map((item, index) => (
          <span className="randomizer-reel__tile" key={index}>
            {item.coverImageId && <img src={igdbCoverSrc(item.coverImageId)} alt="" decoding="async" />}
          </span>
        ))}
      </div>
    </div>
  );
}

const TILE = 150;
const TILE_GAP = 14;
const LANDING_MS = 2200;
const SETTLE_MS = 650;

// The reel's last spin: a still strip that glides left and eases to a stop with the pick (the reel's last
// item) in the middle, which then lights up before the pick card takes over.
function ReelLanding({ items, onDone }: { items: RandomizerSpinResponse["reels"]; onDone: () => void }) {
  const frame = useRef<HTMLDivElement>(null);
  const [offset, setOffset] = useState(0);
  const [stopped, setStopped] = useState(false);
  const pick = items[items.length - 1];
  const others = items.slice(0, -1).length ? items.slice(0, -1) : [pick];
  const before = [...others, ...others, ...others, ...others].slice(0, Math.max(18, others.length * 3));
  const strip = [...before, pick, ...others.slice(0, 6)];
  const pickIndex = before.length;
  useLayoutEffect(() => {
    const width = frame.current?.clientWidth ?? 800;
    const target = width / 2 - (pickIndex * (TILE + TILE_GAP) + TILE / 2);
    const start = window.requestAnimationFrame(() => window.requestAnimationFrame(() => setOffset(target)));
    const stop = setTimeout(() => setStopped(true), LANDING_MS);
    const done = setTimeout(onDone, LANDING_MS + SETTLE_MS);
    return () => {
      window.cancelAnimationFrame(start);
      clearTimeout(stop);
      clearTimeout(done);
    };
  }, []);
  return (
    <div className="randomizer-reel randomizer-reel--landing" ref={frame} aria-label="Landing">
      <div className="randomizer-reel__strip" style={{ transform: `translateX(${offset}px)`, "--landing-ms": `${LANDING_MS}ms` } as CSSProperties}>
        {strip.map((item, index) => (
          <span className={`randomizer-reel__tile${index === pickIndex ? " is-pick" : ""}${index === pickIndex && stopped ? " is-landed" : ""}`} key={index}>
            {item.coverImageId && <img src={igdbCoverSrc(item.coverImageId)} alt="" decoding="async" />}
          </span>
        ))}
      </div>
    </div>
  );
}

function PickCard({ result, onMoreLikeThis, landed = false }: { result: RandomizerSpinResponse; onMoreLikeThis?: (pick: RandomizerPick) => void; landed?: boolean }) {
  const pick = result.pick!;
  const facts = [pick.releaseYear, pick.genres.join(", "), pick.platforms.join(", ")].filter(Boolean);
  return (
    <article className={`randomizer-pick${landed ? " randomizer-pick--landed" : ""}`}>
      <div className="randomizer-pick__cover">
        {pick.coverImageId && <img src={igdbCoverSrc(pick.coverImageId)} alt={`${pick.title} cover`} />}
      </div>
      <div className="randomizer-pick__info">
        <h2>{pick.title}</h2>
        <p className="randomizer-pick__facts">{facts.join(" · ")}</p>
        {pick.totalRating != null && (
          <p className="randomizer-pick__rating">
            IGDB {pick.totalRating}
            {pick.totalRatingCount != null && <small> from {pick.totalRatingCount.toLocaleString()} ratings</small>}
          </p>
        )}
        {pick.themes.length > 0 && <p className="randomizer-pick__themes">{pick.themes.join(", ")}</p>}
        {pick.summary && <p className="randomizer-pick__summary">{pick.summary}</p>}
        <p className="randomizer-pick__meta">
          {pick.url && <a href={pick.url} target="_blank" rel="noreferrer">View on IGDB</a>}
          <span>{result.poolSize.toLocaleString()} games match these filters</span>
        </p>
        {onMoreLikeThis && <p><Button small onClick={() => onMoreLikeThis(pick)}>More like this</Button></p>}
        {result.similarWidened && <p className="state">Few direct matches were left, so this came from games similar to those.</p>}
        {result.repeatAllowed && <p className="state warning">You've seen most of these recently, so recent picks can come back.</p>}
      </div>
    </article>
  );
}

function RecentPicks({ history, onClear }: { history: RandomizerHistoryItem[]; onClear: () => void }) {
  if (history.length === 0) return null;
  return (
    <section className="randomizer-recent" aria-label="Recent picks">
      <div className="randomizer-recent__header">
        <h3>Recent picks</h3>
        <Button small onClick={onClear}>Clear history</Button>
      </div>
      <ol className="randomizer-recent__list">
        {history.map(item => (
          <li key={item.id} title={item.title}>
            {item.coverImageId ? <img src={igdbCoverSrc(item.coverImageId, "small")} alt="" loading="lazy" /> : <span className="randomizer-recent__blank" />}
            <span>{item.title}</span>
          </li>
        ))}
      </ol>
    </section>
  );
}
