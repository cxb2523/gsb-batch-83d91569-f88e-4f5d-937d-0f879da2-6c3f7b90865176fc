import type { ReleaseDetail, ReleaseListItem } from "../../../shared/types";
import type { ApiClient } from "./api/client";
import type { AppShell, AppView } from "./appShell";
import { useDetailSession } from "./detailSession";
import { deleteOneRelease, type ReleaseDeletionMode } from "./releaseDeletion";
import type { ReleaseEditPatch } from "./releaseEditing";

// Release detail page: open, edit, artwork, delete. Every edit adopts the item the server returns.
export type ReleaseDetailWorkflow = ReturnType<typeof useReleaseDetailWorkflow>;

export function useReleaseDetailWorkflow({
  api,
  shell,
  initialDetail,
  reload,
  setView,
  onDeleted
}: {
  api: ApiClient;
  shell: AppShell;
  initialDetail?: ReleaseDetail;
  reload: () => Promise<void>;
  setView: (view: AppView) => void;
  onDeleted: (ids: string[]) => void;
}) {
  const session = useDetailSession<ReleaseListItem, ReleaseDetail>({
    initialDetail,
    load: item => api.getRelease(item.id),
    fallback: item => ({ ...item, sources: [], igdbUrl: null, screenshots: [], trailers: [] }),
    reload,
    shell,
    action: "open-release-detail"
  });

  const openDetail = (item: ReleaseListItem) => {
    setView("detail");
    return session.open(item);
  };

  const showDetail = (item: ReleaseDetail) => {
    session.setDetail(item);
    setView("detail");
  };

  const renameRelease = async (title: string) => {
    if (!title.trim()) return;
    await session.mutate("rename-release", async current => (await api.patchRelease(current.id, { title: title.trim() })).item);
  };

  const editReleaseDetails = async (patch: ReleaseEditPatch) => {
    await session.mutate("edit-release-details", async current => (await api.patchRelease(current.id, { ...patch })).item);
  };

  const setWatched = async (watched: boolean) => {
    await session.mutate(watched ? "watch-release" : "unwatch-release", async current => (await api.patchRelease(current.id, { watched })).item);
  };

  const uploadArtwork = async (file: File | null) => {
    if (!file) return;
    await session.mutate("upload-artwork", async current => {
      const dataBase64 = await fileToBase64(file);
      return (await api.uploadLocalArtwork(current.id, { fileName: file.name, mimeType: file.type, dataBase64 })).item;
    });
  };

  const removeHeroArtwork = async () => {
    const hero = session.detail?.artworks[0];
    if (!hero) return;
    await session.mutate("remove-artwork", async current => (await api.deleteArtwork(current.id, hero.imageId)).item);
  };

  // Swaps the hero with the next artwork.
  const promoteNextArtwork = async () => {
    if (!session.detail || session.detail.artworks.length < 2) return;
    await session.mutate("reorder-artwork", async current => {
      const ids = current.artworks.map(art => art.imageId);
      [ids[0], ids[1]] = [ids[1], ids[0]];
      return (await api.reorderArtworks(current.id, ids)).item;
    });
  };

  const deleteCurrent = async (mode: ReleaseDeletionMode) => {
    const detail = session.detail;
    if (!detail) return;
    const result = await deleteOneRelease(detail, mode, {
      confirm: shell.dialogs.confirm,
      alert: shell.dialogs.alert,
      deleteRelease: (id, block) => api.deleteRelease(id, block),
      log: shell.logUiEvent
    });
    if (result.status !== "deleted") return;
    session.close();
    setView("gallery");
    onDeleted(result.deletedIds);
    await reload();
  };

  return {
    detail: session.detail,
    actions: { openDetail, showDetail, renameRelease, editReleaseDetails, setWatched, uploadArtwork, removeHeroArtwork, promoteNextArtwork, deleteCurrent }
  };
}

function fileToBase64(file: File) {
  return new Promise<string>((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(reader.error);
    reader.onload = () => {
      const result = String(reader.result ?? "");
      resolve(result.includes(",") ? result.split(",").pop() ?? "" : result);
    };
    reader.readAsDataURL(file);
  });
}
