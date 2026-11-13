import { useMemo, useState } from "react";

// Multi-select state for a collection list; used inside useCollectionWorkspace.

export interface CollectionSelection {
  selectedIds: Set<string>;
  selectedVisibleCount: number;
  toggle(id: string, selected: boolean): void;
  selectAllVisible(): void;
  clearSelection(): void;
  removeIds(ids: string[]): void;
}

export function useCollectionSelection(visibleIds: string[]): CollectionSelection {
  const [selectedIds, setSelectedIds] = useState<Set<string>>(() => new Set());
  const visibleIdSet = useMemo(() => new Set(visibleIds), [visibleIds]);
  const selectedVisibleCount = useMemo(
    () => [...selectedIds].filter(id => visibleIdSet.has(id)).length,
    [selectedIds, visibleIdSet]
  );

  const toggle = (id: string, selected: boolean) => {
    setSelectedIds(current => {
      const next = new Set(current);
      if (selected) next.add(id);
      else next.delete(id);
      return next;
    });
  };

  const selectAllVisible = () => {
    setSelectedIds(current => {
      const next = new Set(current);
      for (const id of visibleIds) next.add(id);
      return next;
    });
  };

  const clearSelection = () => {
    setSelectedIds(new Set());
  };

  const removeIds = (ids: string[]) => {
    setSelectedIds(current => {
      const next = new Set(current);
      for (const id of ids) next.delete(id);
      return next;
    });
  };

  return {
    selectedIds,
    selectedVisibleCount,
    toggle,
    selectAllVisible,
    clearSelection,
    removeIds
  };
}
