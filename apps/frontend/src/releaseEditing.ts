import type { ReleaseDetail } from "../../../shared/types";

export interface ReleaseEditPatch {
  title?: string;
  publishers?: string;
  developers?: string;
  platforms?: string;
  category?: string;
  dateText?: string;
  releaseDate?: string;
  datePrecision?: string;
  releaseWindow?: string;
}

export function createReleaseFieldDraft(detail: ReleaseDetail): ReleaseEditPatch {
  return {
    publishers: detail.publishers.join(", "),
    developers: detail.developers.join(", "),
    platforms: detail.platforms.join(", "),
    category: detail.category,
    dateText: detail.dateText,
    releaseDate: detail.releaseDate ?? "",
    datePrecision: detail.datePrecision,
    releaseWindow: detail.releaseWindow ?? ""
  };
}

export function buildReleaseEditPatch(detail: ReleaseDetail, draft: ReleaseEditPatch): ReleaseEditPatch {
  const patch: ReleaseEditPatch = {};
  if (draft.publishers !== undefined && draft.publishers !== detail.publishers.join(", ")) patch.publishers = draft.publishers;
  if (draft.developers !== undefined && draft.developers !== detail.developers.join(", ")) patch.developers = draft.developers;
  if (draft.platforms !== undefined && draft.platforms !== detail.platforms.join(", ")) patch.platforms = draft.platforms;
  if (draft.category !== undefined && draft.category !== detail.category) patch.category = draft.category;
  if (draft.dateText !== undefined && draft.dateText !== detail.dateText) patch.dateText = draft.dateText;
  if (draft.releaseDate !== undefined && draft.releaseDate !== (detail.releaseDate ?? "")) patch.releaseDate = draft.releaseDate;
  if (draft.datePrecision !== undefined && draft.datePrecision !== detail.datePrecision) patch.datePrecision = draft.datePrecision;
  if (draft.releaseWindow !== undefined && draft.releaseWindow !== (detail.releaseWindow ?? "")) patch.releaseWindow = draft.releaseWindow;
  return patch;
}
