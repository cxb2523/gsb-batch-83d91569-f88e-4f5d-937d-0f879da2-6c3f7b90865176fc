import { useEffect, useMemo, useRef, useState } from "react";
import { createDebounced } from "./api/debounce";
import type { AppView } from "./appShell";
import type { DeletionResult } from "./collectionDeletion";
import { filterByGenre, genreOptions } from "./genreFilter";
import { useCollectionSelection } from "./collectionSelection";

export type CollectionWorkspace<Item extends { id: string }, Filters> = ReturnType<typeof useCollectionWorkspace<Item, Filters>>;

// Where to take the user back to after a detail page: the list view they came from and the item they opened.
interface ReturnPosition {
  view: AppView;
  itemId: string;
  scrollY: number;
}

// Browsing behaviour shared by Upcoming and the Completed Library: server-side filters with a
// debounced search, the client-side genre filter, multi-select with Ctrl+A, bulk-delete bookkeeping,
// and the way back from a detail page to the same list and scroll position.
// Each collection supplies how to load and how to delete; this module owns everything in between.
export function useCollectionWorkspace<Item extends { id: string }, Filters>({
  items,
  initialFilters,
  load,
  genresOf,
  view,
  setView,
  listViews,
  detailView,
  itemAttribute,
  log
}: {
  items: Item[];
  initialFilters: Filters;
  load: (filters: Filters) => Promise<void>;
  genresOf: (item: Item) => string[];
  view: AppView;
  setView: (view: AppView) => void;
  // The views that show this collection. The first is its home: Ctrl+A works there, and it is where
  // "back" goes when there is no remembered position.
  listViews: readonly AppView[];
  detailView: AppView;
  // The data attribute each rendered item carries, used to scroll back to the item that was opened.
  itemAttribute: string;
  log?: (event: string, details: Record<string, unknown>) => void;
}) {
  const [filters, setFilters] = useState<Filters>(initialFilters);
  const [genre, setGenre] = useState("");
  const latest = useRef({ filters, load });
  latest.current = { filters, load };
  const homeView = listViews[0];
  const active = view === homeView;

  const genres = useMemo(() => genreOptions(items, genresOf), [items]);
  const visibleItems = useMemo(() => filterByGenre(items, genre, genresOf), [items, genre]);
  const visibleIds = useMemo(() => visibleItems.map(item => item.id), [visibleItems]);
  const selection = useCollectionSelection(visibleIds);
  const returnPosition = useReturnPosition({ view, detailView, itemAttribute, rendered: visibleItems });

  const applyFilters = (next: Filters) => {
    setFilters(next);
    void latest.current.load(next);
  };

  const setFilter = <Key extends keyof Filters>(key: Key, value: Filters[Key]) => {
    applyFilters({ ...latest.current.filters, [key]: value });
  };

  const debouncedSearch = useMemo(() => createDebounced((search: string) => {
    applyFilters({ ...latest.current.filters, search });
  }, 250), []);

  const reload = () => latest.current.load(latest.current.filters);

  const selectAllVisible = () => {
    log?.("ui.click", { action: "select-all", count: visibleIds.length });
    selection.selectAllVisible();
  };

  const clearSelection = () => {
    log?.("ui.click", { action: "clear-selection", count: selection.selectedVisibleCount });
    selection.clearSelection();
  };

  useEffect(() => {
    if (!active || typeof document === "undefined") return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (!event.ctrlKey || event.key.toLowerCase() !== "a") return;
      const target = event.target as { tagName?: unknown } | null;
      const tagName = typeof target?.tagName === "string" ? target.tagName.toUpperCase() : "";
      if (["INPUT", "TEXTAREA", "SELECT"].includes(tagName)) return;
      event.preventDefault();
      selection.selectAllVisible();
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [active, visibleIds.join("|")]);

  // Runs a collection-specific deletion over the selected visible items, then prunes the selection and reloads.
  const deleteSelected = async (run: (selected: Item[]) => Promise<DeletionResult>) => {
    const selected = visibleItems.filter(item => selection.selectedIds.has(item.id));
    if (selected.length === 0) return;
    const result = await run(selected);
    if (result.deletedIds.length === 0) return;
    if (result.status === "deleted") selection.clearSelection();
    else selection.removeIds(result.deletedIds);
    await reload();
  };

  // Call when opening an item's detail page, before navigating to it.
  const rememberReturnPosition = (itemId: string) => {
    returnPosition.set({
      view: listViews.includes(view) ? view : homeView,
      itemId,
      scrollY: globalThis.window?.scrollY ?? 0
    });
  };

  const returnToList = () => setView(returnPosition.current?.view ?? homeView);

  return {
    // Everything loaded, before the genre filter.
    loadedCount: items.length,
    filters,
    setFilter,
    debouncedSearch,
    reload,
    genre,
    genres,
    setGenre,
    visibleItems,
    selectedIds: selection.selectedIds,
    selectedVisibleCount: selection.selectedVisibleCount,
    toggleSelection: selection.toggle,
    selectAllVisible,
    clearSelection,
    removeFromSelection: selection.removeIds,
    deleteSelected,
    rememberReturnPosition,
    returnToList
  };
}

// Scrolls back to the remembered item once its list view is showing again, then forgets it. Leaving for
// any view other than the detail page or the remembered list forgets it too.
function useReturnPosition({ view, detailView, itemAttribute, rendered }: { view: AppView; detailView: AppView; itemAttribute: string; rendered: unknown }) {
  const [current, set] = useState<ReturnPosition | null>(null);

  useEffect(() => {
    if (current && view !== detailView && view !== current.view) set(null);
  }, [view, current]);

  useEffect(() => {
    if (!current || view !== current.view) return;
    const frame = globalThis.window?.requestAnimationFrame?.(() => {
      const element = globalThis.document?.querySelector(`[${itemAttribute}="${cssAttributeValue(current.itemId)}"]`);
      if (element instanceof globalThis.window.HTMLElement) {
        element.scrollIntoView({ block: "center", inline: "nearest" });
      } else {
        globalThis.window?.scrollTo?.(0, current.scrollY);
      }
      set(null);
    });
    return () => {
      if (frame !== undefined) globalThis.window?.cancelAnimationFrame?.(frame);
    };
  }, [current, view, rendered]);

  return { current, set };
}

function cssAttributeValue(value: string) {
  return value.replace(/\\/g, "\\\\").replace(/"/g, '\\"');
}
