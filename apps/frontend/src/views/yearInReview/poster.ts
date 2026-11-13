import type { YearInReviewGame, YearInReviewSummary } from "../../../../../shared/types";
import { formatRating, plural } from "./parts";

// Save as image draws every game finished in the year onto one image. Horizontal is a 1920×1080 cover grid
// for screens. Vertical is made for a phone's Reddit feed: a dense 1080-wide grid (6–7 covers a row for a
// typical year) about a phone screen tall, with each name in bold and the platform on its own line, sized to
// read at a glance when the feed shows the image at phone width. Covers come through the backend's cover cache
// (same origin), so the canvas can be exported.

export type PosterOrientation = "horizontal" | "vertical";

export const POSTER_FORMATS: Record<PosterOrientation, { label: string; detail: string }> = {
  horizontal: { label: "Horizontal", detail: "1920 × 1080 · for screens" },
  vertical: { label: "Vertical", detail: "Readable on phones · for Reddit" }
};

const HORIZONTAL = { width: 1920, height: 1080 };

// The poster's size, margin and title area; both layouts have one.
interface PosterFrame {
  width: number;
  height: number;
  padding: number;
  header: { top: number; height: number };
}

interface PosterTile {
  x: number;
  y: number;
  width: number;
  // The cover is width × width·4/3; the caption sits under it.
  coverHeight: number;
  captionSize: number;
}

interface PosterLayout extends PosterFrame {
  columns: number;
  tiles: PosterTile[];
}

const COVER_RATIO = 4 / 3;
const CAPTION_LINES = 2;
const captionSizeFor = (tileWidth: number) => Math.round(Math.min(22, Math.max(11, tileWidth * 0.11)));
const captionHeightFor = (size: number) => Math.ceil(size * 1.25 * CAPTION_LINES + size * 0.6);

// Horizontal: the biggest tiles that fit every game on the 1920×1080 poster, each row centred.
export function posterLayout(count: number): PosterLayout {
  const { width, height } = HORIZONTAL;
  const padding = Math.round(Math.min(width, height) * 0.045);
  const headerHeight = Math.round(height * 0.17);
  const gridTop = padding + headerHeight;
  const available = { width: width - padding * 2, height: height - gridTop - padding * 1.4 };
  let best: { columns: number; tileWidth: number; gap: number } | null = null;
  for (let columns = 1; columns <= Math.max(1, count); columns += 1) {
    const rows = Math.ceil(count / columns);
    const gap = Math.max(8, Math.round((available.width / columns) * 0.1));
    const tileWidth = (available.width - gap * (columns - 1)) / columns;
    const tileHeight = tileWidth * COVER_RATIO + captionHeightFor(captionSizeFor(tileWidth));
    const fits = rows * tileHeight + (rows - 1) * gap <= available.height;
    if (fits && (!best || tileWidth > best.tileWidth)) best = { columns, tileWidth, gap };
  }
  // Too many games even at one per column's width: shrink until they fit.
  if (!best) {
    const columns = Math.max(1, Math.ceil(Math.sqrt(count * (available.width / available.height) * COVER_RATIO)));
    const rows = Math.ceil(count / columns);
    const gap = 6;
    const tileWidth = Math.min((available.width - gap * (columns - 1)) / columns, ((available.height - gap * (rows - 1)) / rows - captionHeightFor(11)) / COVER_RATIO);
    best = { columns, tileWidth: Math.max(8, tileWidth), gap };
  }
  const { columns, gap } = best;
  const tileWidth = Math.floor(best.tileWidth);
  const captionSize = captionSizeFor(tileWidth);
  const coverHeight = Math.round(tileWidth * COVER_RATIO);
  const rowHeight = coverHeight + captionHeightFor(captionSize) + gap;
  // Centre the grid in the space under the header, so a short year doesn't leave an empty band at the bottom.
  const rows = Math.ceil(count / columns);
  const gridTopCentred = gridTop + Math.max(0, (available.height - (rows * rowHeight - gap)) / 2);
  const tiles: PosterTile[] = [];
  for (let index = 0; index < count; index += 1) {
    const row = Math.floor(index / columns);
    const inRow = Math.min(columns, count - row * columns);
    const rowWidth = inRow * tileWidth + (inRow - 1) * gap;
    const left = padding + (available.width - rowWidth) / 2;
    tiles.push({ x: Math.round(left + (index % columns) * (tileWidth + gap)), y: Math.round(gridTopCentred + row * rowHeight), width: tileWidth, coverHeight, captionSize });
  }
  return { width, height, padding, header: { top: padding, height: headerHeight }, columns, tiles };
}

// Vertical (phones): sizes are image pixels on a 1080-wide image, which a phone feed shows about 390pt wide,
// so text needs about 24px or more to read as 9pt at a glance.
export const PHONE = { width: 1080, padding: 26, headerHeight: 175, gap: 12, rowGap: 18, footer: 20, minTitle: 24, maxTitle: 34, titleLines: 2 } as const;

// More games, more covers a row, so a year stays about a phone screen tall.
export const phoneColumns = (count: number) => (count <= 8 ? 4 : count <= 15 ? 5 : count <= 30 ? 6 : count <= 70 ? 7 : 8);

interface PhoneTile {
  x: number;
  y: number;
  width: number;
  coverHeight: number;
  titleSize: number;
  platformSize: number;
}

interface PhoneLayout extends PosterFrame {
  columns: number;
  phoneTiles: PhoneTile[];
}

export function phoneLayout(count: number): PhoneLayout {
  const { width, padding, headerHeight, gap, rowGap, footer, minTitle, maxTitle, titleLines } = PHONE;
  const columns = phoneColumns(count);
  const tileWidth = Math.floor((width - padding * 2 - gap * (columns - 1)) / columns);
  const coverHeight = Math.round(tileWidth * COVER_RATIO);
  const titleSize = Math.round(Math.min(maxTitle, Math.max(minTitle, tileWidth * 0.175)));
  const platformSize = Math.round(titleSize * 0.92);
  const textHeight = Math.ceil(titleSize * 1.12 * titleLines + platformSize * 1.25 + 8);
  const rowHeight = coverHeight + textHeight + rowGap;
  const top = padding + headerHeight;
  const rows = Math.ceil(count / columns);
  const phoneTiles = Array.from({ length: count }, (_, index) => {
    const row = Math.floor(index / columns);
    const inRow = Math.min(columns, count - row * columns);
    const rowWidth = inRow * tileWidth + (inRow - 1) * gap;
    const left = (width - rowWidth) / 2;
    return { x: Math.round(left + (index % columns) * (tileWidth + gap)), y: top + row * rowHeight, width: tileWidth, coverHeight, titleSize, platformSize };
  });
  const height = top + rows * rowHeight - rowGap + footer + padding;
  return { width, height, padding, header: { top: padding, height: headerHeight }, columns, phoneTiles };
}

const GOLD = "#f3d27a";
const INK = "#f4ecdc";
const MUTED = "#cfc3ab";
// Every weight and family the poster draws with.
const POSTER_FONTS = ['700 64px "Cinzel Decorative"', '400 20px "Cinzel"', '700 20px "Cinzel"', '400 20px "Alegreya Sans"', '700 20px "Alegreya Sans"'];

// Draws the poster and returns it as PNG bytes. `coverSrc` gives a same-origin URL for an IGDB cover id.
export async function drawPoster({ summary, orientation, coverSrc }: {
  summary: YearInReviewSummary;
  orientation: PosterOrientation;
  coverSrc: (imageId: string) => string;
}): Promise<Uint8Array> {
  const gotyId = summary.goty?.game.id ?? null;
  const layout = orientation === "horizontal" ? posterLayout(summary.games.length) : phoneLayout(summary.games.length);
  const canvas = document.createElement("canvas");
  canvas.width = layout.width;
  canvas.height = layout.height;
  const context = canvas.getContext("2d");
  if (!context) throw new Error("Couldn't draw the image");
  // A canvas draws in a fallback font when the web font is not loaded yet.
  await Promise.all(POSTER_FONTS.map(font => document.fonts?.load?.(font).catch(() => undefined)));

  const covers = new Map<string, HTMLImageElement | null>();
  await Promise.all(summary.games.map(async game => {
    if (game.coverImageId && !covers.has(game.coverImageId)) covers.set(game.coverImageId, await loadImage(coverSrc(game.coverImageId)));
  }));
  const coverOf = (game: YearInReviewGame) => (game.coverImageId ? covers.get(game.coverImageId) ?? null : null);
  const gotyCover = summary.goty ? coverOf(summary.goty.game) : null;

  drawBackdrop(context, layout, gotyCover);
  drawHeader(context, layout, summary);
  if ("tiles" in layout) {
    summary.games.forEach((game, index) => drawTile(context, layout.tiles[index], game, coverOf(game), game.id === gotyId));
  } else {
    // The GOTY leads the grid; the rest follow in finish order.
    const ordered = [...summary.games].sort((left, right) => Number(right.id === gotyId) - Number(left.id === gotyId));
    ordered.forEach((game, index) => drawPhoneTile(context, layout.phoneTiles[index], game, coverOf(game), game.id === gotyId));
  }

  const blob = await new Promise<Blob | null>(resolve => canvas.toBlob(resolve, "image/png"));
  if (!blob) throw new Error("Couldn't draw the image");
  return new Uint8Array(await blob.arrayBuffer());
}

function loadImage(src: string) {
  return new Promise<HTMLImageElement | null>(resolve => {
    const image = new Image();
    image.onload = () => resolve(image);
    image.onerror = () => resolve(null);
    image.src = src;
  });
}

// The GOTY's cover, blurred across the whole poster under a dark wash; plain night without one.
function drawBackdrop(context: CanvasRenderingContext2D, { width, height }: PosterFrame, cover: HTMLImageElement | null) {
  const night = context.createLinearGradient(0, 0, width, height);
  night.addColorStop(0, "#130b26");
  night.addColorStop(1, "#07060c");
  context.fillStyle = night;
  context.fillRect(0, 0, width, height);
  if (cover) {
    // Across the first screenful only; a tall phone image fades into night below.
    const glowHeight = Math.min(height, width * 1.4);
    context.save();
    context.filter = "blur(48px) saturate(1.2)";
    context.globalAlpha = 0.55;
    drawCovered(context, cover, -80, -80, width + 160, glowHeight + 160);
    context.restore();
    const fade = context.createLinearGradient(0, glowHeight * 0.6, 0, glowHeight + 80);
    fade.addColorStop(0, "rgba(10,8,20,0)");
    fade.addColorStop(1, "#0a0814");
    context.fillStyle = fade;
    context.fillRect(0, glowHeight * 0.6, width, height - glowHeight * 0.6);
  }
  const wash = context.createLinearGradient(0, 0, 0, height);
  wash.addColorStop(0, "rgba(7,6,12,.55)");
  wash.addColorStop(1, "rgba(7,6,12,.85)");
  context.fillStyle = wash;
  context.fillRect(0, 0, width, height);
  context.strokeStyle = "rgba(243,210,122,.45)";
  context.lineWidth = 2;
  const inset = Math.round(Math.min(width, height) * 0.018);
  context.strokeRect(inset, inset, width - inset * 2, height - inset * 2);
}

function drawHeader(context: CanvasRenderingContext2D, layout: PosterFrame, summary: YearInReviewSummary) {
  const { width, padding, header } = layout;
  const titleSize = Math.round(header.height * 0.42);
  context.textAlign = "center";
  context.textBaseline = "alphabetic";
  context.fillStyle = GOLD;
  context.font = `700 ${titleSize}px "Cinzel Decorative", Georgia, serif`;
  context.shadowColor = "rgba(0,0,0,.6)";
  context.shadowBlur = 18;
  context.fillText(`My ${summary.year} in Games`, width / 2, header.top + titleSize, width - padding * 2);
  context.shadowBlur = 0;
  const subtitleSize = Math.round(titleSize * 0.38);
  context.fillStyle = MUTED;
  context.font = `400 ${subtitleSize}px "Alegreya Sans", "Segoe UI", sans-serif`;
  const goty = summary.goty?.game.title;
  const subtitle = [`${plural(summary.count, "game")} finished${summary.inProgress ? " so far" : ""}`, goty && `Game of the Year: ${goty}`].filter(Boolean).join("   ·   ");
  context.fillText(subtitle, width / 2, header.top + titleSize + subtitleSize * 1.7, width - padding * 2);
}

// How one poster layout draws a cover's frame; sizes are in poster pixels.
interface CoverFrameStyle {
  shadowBlur: number;
  shadowOffsetY: number;
  goldWidth: number;
  crownOffset: number;
  crownWidth: number;
  ratingSize: number;
  initialWhenMissing: boolean;
}

function drawCoverFrame(context: CanvasRenderingContext2D, box: Pick<PosterTile, "x" | "y" | "width" | "coverHeight">, game: YearInReviewGame, cover: HTMLImageElement | null, isGoty: boolean, style: CoverFrameStyle) {
  const { x, y, width, coverHeight } = box;
  context.save();
  context.shadowColor = "rgba(0,0,0,.6)";
  context.shadowBlur = style.shadowBlur;
  context.shadowOffsetY = style.shadowOffsetY;
  context.fillStyle = "#1a1530";
  context.fillRect(x, y, width, coverHeight);
  context.restore();
  if (cover) drawCovered(context, cover, x, y, width, coverHeight);
  else if (style.initialWhenMissing) {
    context.fillStyle = MUTED;
    context.font = `400 ${Math.round(width * 0.35)}px "Cinzel", Georgia, serif`;
    context.textAlign = "center";
    context.textBaseline = "middle";
    context.fillText(game.title.slice(0, 1), x + width / 2, y + coverHeight / 2);
  }
  context.strokeStyle = isGoty ? GOLD : "rgba(255,255,255,.18)";
  context.lineWidth = isGoty ? style.goldWidth : 1;
  context.strokeRect(x, y, width, coverHeight);
  if (isGoty) drawCrown(context, x + width / 2, y - style.crownOffset, style.crownWidth);
  if (game.ratingScore !== null) drawRating(context, x + width, y, formatRating(game.ratingScore), style.ratingSize);
}

function drawTile(context: CanvasRenderingContext2D, tile: PosterTile, game: YearInReviewGame, cover: HTMLImageElement | null, isGoty: boolean) {
  const { x, y, width, coverHeight, captionSize } = tile;
  drawCoverFrame(context, tile, game, cover, isGoty, {
    shadowBlur: 16,
    shadowOffsetY: 6,
    goldWidth: Math.max(3, width * 0.025),
    crownOffset: Math.max(6, width * 0.05),
    crownWidth: Math.max(18, width * 0.28),
    ratingSize: captionSize,
    initialWhenMissing: true
  });

  context.textAlign = "left";
  context.textBaseline = "top";
  const lines = wrapCaption(context, game.title, game.userPlatform, width, captionSize);
  lines.forEach((line, index) => {
    const lineY = y + coverHeight + captionSize * 0.5 + index * captionSize * 1.25;
    context.font = `400 ${captionSize}px "Alegreya Sans", "Segoe UI", sans-serif`;
    context.fillStyle = INK;
    context.fillText(line.title, x, lineY);
    if (line.platform) {
      context.fillStyle = MUTED;
      context.fillText(line.platform, x + context.measureText(line.title).width, lineY);
    }
  });
}

// A phone tile: the cover with its rating, then the name in bold (two lines at most) and the platform.
function drawPhoneTile(context: CanvasRenderingContext2D, tile: PhoneTile, game: YearInReviewGame, cover: HTMLImageElement | null, isGoty: boolean) {
  const { x, y, width, coverHeight, titleSize, platformSize } = tile;
  drawCoverFrame(context, tile, game, cover, isGoty, {
    shadowBlur: 12,
    shadowOffsetY: 4,
    goldWidth: 5,
    crownOffset: 4,
    crownWidth: Math.max(26, width * 0.3),
    ratingSize: Math.round(titleSize * 0.85),
    initialWhenMissing: false
  });

  context.textAlign = "left";
  context.textBaseline = "top";
  context.fillStyle = isGoty ? GOLD : INK;
  context.font = `700 ${titleSize}px "Alegreya Sans", "Segoe UI", sans-serif`;
  let textY = y + coverHeight + 7;
  for (const line of wrapLines(context, game.title, width, PHONE.titleLines)) {
    context.fillText(line, x, textY);
    textY += titleSize * 1.12;
  }
  if (game.userPlatform) {
    context.fillStyle = "#d9c08a";
    context.font = `400 ${platformSize}px "Alegreya Sans", "Segoe UI", sans-serif`;
    const platform = context.measureText(game.userPlatform).width > width ? fitWithEllipsis(context, game.userPlatform, width) : game.userPlatform;
    context.fillText(platform, x, textY + 2);
  }
}

function wrapWords(context: CanvasRenderingContext2D, text: string, width: number): string[] {
  const lines: string[] = [];
  let current = "";
  for (const word of text.split(" ")) {
    const next = current ? `${current} ${word}` : word;
    if (context.measureText(next).width <= width || !current) current = next;
    else {
      lines.push(current);
      current = word;
    }
  }
  if (current) lines.push(current);
  return lines;
}

// Words into at most `maxLines` lines of `width`, the last cut with "…" when it doesn't all fit.
function wrapLines(context: CanvasRenderingContext2D, text: string, width: number, maxLines: number) {
  const lines = wrapWords(context, text.replace(/\s+/g, " "), width);
  const shown = lines.slice(0, maxLines).map(line => (context.measureText(line).width > width ? fitWithEllipsis(context, line, width) : line));
  if (lines.length > maxLines) shown[maxLines - 1] = fitWithEllipsis(context, `${shown[maxLines - 1]}…`, width);
  return shown;
}

// "Title (Platform)" in at most two lines; the platform stays muted and the end is cut with "…".
function wrapCaption(context: CanvasRenderingContext2D, title: string, platform: string, width: number, size: number) {
  context.font = `400 ${size}px "Alegreya Sans", "Segoe UI", sans-serif`;
  const suffix = platform ? ` (${platform})` : "";
  const lines = wrapWords(context, `${title}${suffix}`, width);
  let shown = lines.slice(0, CAPTION_LINES);
  if (lines.length > CAPTION_LINES) {
    shown[CAPTION_LINES - 1] = fitWithEllipsis(context, `${shown[CAPTION_LINES - 1]}…`, width);
  }
  shown = shown.map(line => (context.measureText(line).width > width ? fitWithEllipsis(context, line, width) : line));
  // Split each line where the platform starts, so it can be drawn muted. Starts come from the full lines,
  // before any "…" shortened them.
  const starts = lines.map((_, index) => lines.slice(0, index).reduce((sum, line) => sum + line.length + 1, 0));
  return shown.map((line, index) => {
    const cut = Math.max(0, Math.min(line.length, title.length - starts[index]));
    return { title: line.slice(0, cut), platform: line.slice(cut) };
  });
}

function fitWithEllipsis(context: CanvasRenderingContext2D, text: string, width: number) {
  let cut = text.replace(/…$/, "");
  while (cut && context.measureText(`${cut}…`).width > width) cut = cut.slice(0, -1);
  return `${cut}…`;
}

function drawRating(context: CanvasRenderingContext2D, right: number, top: number, label: string, size: number) {
  const fontSize = Math.max(11, Math.round(size * 0.95));
  context.font = `700 ${fontSize}px "Cinzel", Georgia, serif`;
  const padX = fontSize * 0.45;
  const badgeWidth = context.measureText(label).width + padX * 2;
  const badgeHeight = fontSize * 1.5;
  const x = right - badgeWidth - fontSize * 0.35;
  const y = top + fontSize * 0.35;
  context.fillStyle = "rgba(0,0,0,.72)";
  context.fillRect(x, y, badgeWidth, badgeHeight);
  context.strokeStyle = GOLD;
  context.lineWidth = 1;
  context.strokeRect(x, y, badgeWidth, badgeHeight);
  context.fillStyle = GOLD;
  context.textAlign = "center";
  context.textBaseline = "middle";
  context.fillText(label, x + badgeWidth / 2, y + badgeHeight / 2 + 1);
}

function drawCrown(context: CanvasRenderingContext2D, centerX: number, bottom: number, width: number) {
  const height = width * 0.62;
  const left = centerX - width / 2;
  const top = bottom - height;
  context.save();
  context.fillStyle = GOLD;
  context.shadowColor = "rgba(243,210,122,.7)";
  context.shadowBlur = 12;
  context.beginPath();
  context.moveTo(left, bottom);
  context.lineTo(left, top + height * 0.2);
  context.lineTo(left + width * 0.25, top + height * 0.55);
  context.lineTo(centerX, top);
  context.lineTo(left + width * 0.75, top + height * 0.55);
  context.lineTo(left + width, top + height * 0.2);
  context.lineTo(left + width, bottom);
  context.closePath();
  context.fill();
  context.restore();
}

// Draws the image to fill the box, cropping the overflow (object-fit: cover).
function drawCovered(context: CanvasRenderingContext2D, image: HTMLImageElement, x: number, y: number, width: number, height: number) {
  const scale = Math.max(width / image.naturalWidth, height / image.naturalHeight);
  const sourceWidth = width / scale;
  const sourceHeight = height / scale;
  context.drawImage(image, (image.naturalWidth - sourceWidth) / 2, (image.naturalHeight - sourceHeight) / 2, sourceWidth, sourceHeight, x, y, width, height);
}
