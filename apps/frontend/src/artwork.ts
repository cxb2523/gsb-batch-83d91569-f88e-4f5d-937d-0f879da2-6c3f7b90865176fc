import type { ReleaseListItem } from "../../../shared/types";

// The single place that knows IGDB's image CDN URL shape.
const igdbImageUrl = (imageId: string, imageSize: string) =>
  `https://images.igdb.com/igdb/image/upload/${imageSize}/${imageId}.jpg`;

// The IGDB size for each place a release image shows, for covers and for other artwork.
// A blurred backdrop loses its detail anyway, so it takes a small image that decodes fast.
const artworkSizes = {
  small: { cover: "t_cover_small", art: "t_screenshot_med" },
  grid: { cover: "t_cover_big", art: "t_screenshot_med" },
  detail: { cover: "t_1080p", art: "t_1080p" },
  backdrop: { cover: "t_screenshot_med", art: "t_screenshot_med" }
} as const;

type Artwork = ReleaseListItem["artworks"][number];

export const artworkSrc = (artwork: Artwork, size: keyof typeof artworkSizes, apiBaseUrl: string) => {
  if (artwork.source === "local" && artwork.url) return new URL(artwork.url, apiBaseUrl).toString();
  if (artwork.source === "steamgriddb" && artwork.url) return artwork.url;
  return igdbImageUrl(artwork.imageId, artworkSizes[size][artwork.source === "cover" ? "cover" : "art"]);
};

const coverSizes = { small: "t_cover_small", big: "t_cover_big", detail: "t_cover_big_2x" } as const;

export const igdbCoverSrc = (imageId: string, size: keyof typeof coverSizes = "big") =>
  igdbImageUrl(imageId, coverSizes[size]);

// Grid covers: the big cover on standard screens, the 2x cover on high-DPI (scaled) screens.
export const igdbCoverSrcSet = (imageId: string) =>
  `${igdbImageUrl(imageId, coverSizes.big)} 1x, ${igdbImageUrl(imageId, coverSizes.detail)} 2x`;

export const igdbCoverGridSrcSet = (imageId: string) =>
  `${igdbCoverSrc(imageId, "big")} 264w, ${igdbCoverSrc(imageId, "detail")} 528w`;

// A cover through the backend's cover cache: downloaded once into app data, then served same-origin,
// so the page can read its colours (detail-page tint) and it still shows offline.
export const cachedCoverSrc = (imageId: string, apiBaseUrl: string) =>
  new URL(`/api/covers/${encodeURIComponent(imageId)}`, apiBaseUrl).toString();

export const screenshotSrc = (imageId: string, size: "hero" | "thumb" = "thumb") =>
  igdbImageUrl(imageId, size === "hero" ? "t_1080p" : "t_screenshot_med");
