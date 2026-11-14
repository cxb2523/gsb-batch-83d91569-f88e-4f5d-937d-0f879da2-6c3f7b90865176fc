import path from "node:path";

const MIME_BY_EXTENSION = new Map([
  [".aac", "audio/aac"],
  [".avi", "video/x-msvideo"],
  [".avif", "image/avif"],
  [".bmp", "image/bmp"],
  [".csv", "text/csv"],
  [".doc", "application/msword"],
  [".docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"],
  [".gif", "image/gif"],
  [".heic", "image/heic"],
  [".heif", "image/heif"],
  [".html", "text/html"],
  [".jpeg", "image/jpeg"],
  [".jpg", "image/jpeg"],
  [".json", "application/json"],
  [".m4a", "audio/mp4"],
  [".m4v", "video/mp4"],
  [".md", "text/markdown"],
  [".mkv", "video/x-matroska"],
  [".mov", "video/quicktime"],
  [".mp3", "audio/mpeg"],
  [".mp4", "video/mp4"],
  [".mpeg", "video/mpeg"],
  [".mpg", "video/mpeg"],
  [".oga", "audio/ogg"],
  [".ogg", "audio/ogg"],
  [".ogv", "video/ogg"],
  [".pdf", "application/pdf"],
  [".png", "image/png"],
  [".svg", "image/svg+xml"],
  [".tif", "image/tiff"],
  [".tiff", "image/tiff"],
  [".txt", "text/plain"],
  [".wav", "audio/wav"],
  [".webm", "video/webm"],
  [".webp", "image/webp"],
  [".xml", "application/xml"],
  [".zip", "application/zip"],
]);

function ascii(buffer, start, length) {
  return buffer.subarray(start, start + length).toString("ascii");
}

export function sniffMime(buffer) {
  if (!Buffer.isBuffer(buffer) || buffer.length === 0) return undefined;
  if (buffer.length >= 8 && buffer.subarray(0, 8).equals(Buffer.from("89504e470d0a1a0a", "hex"))) {
    return "image/png";
  }
  if (buffer.length >= 3 && buffer[0] === 0xff && buffer[1] === 0xd8 && buffer[2] === 0xff) {
    return "image/jpeg";
  }
  if (buffer.length >= 6 && ["GIF87a", "GIF89a"].includes(ascii(buffer, 0, 6))) return "image/gif";
  if (buffer.length >= 12 && ascii(buffer, 0, 4) === "RIFF") {
    const kind = ascii(buffer, 8, 4);
    if (kind === "WEBP") return "image/webp";
    if (kind === "WAVE") return "audio/wav";
    if (kind === "AVI ") return "video/x-msvideo";
  }
  if (buffer.length >= 12 && ascii(buffer, 4, 4) === "ftyp") {
    const brand = ascii(buffer, 8, 4).toLowerCase();
    if (brand.includes("heic") || brand.includes("heix")) return "image/heic";
    if (brand.includes("heif") || brand.includes("mif1")) return "image/heif";
    if (brand.includes("avif") || brand.includes("avis")) return "image/avif";
    if (brand.startsWith("qt")) return "video/quicktime";
    if (brand.startsWith("m4a")) return "audio/mp4";
    return "video/mp4";
  }
  if (buffer.length >= 4 && ascii(buffer, 0, 4) === "%PDF") return "application/pdf";
  if (buffer.length >= 4 && buffer.subarray(0, 4).equals(Buffer.from("504b0304", "hex"))) {
    return "application/zip";
  }
  if (buffer.length >= 4 && ascii(buffer, 0, 4) === "OggS") return "application/ogg";
  if (buffer.length >= 3 && ascii(buffer, 0, 3) === "ID3") return "audio/mpeg";
  if (buffer.length >= 2 && buffer[0] === 0xff && (buffer[1] & 0xe0) === 0xe0) return "audio/mpeg";
  if (buffer.length >= 4 && buffer.subarray(0, 4).equals(Buffer.from("1a45dfa3", "hex"))) {
    return "video/webm";
  }
  return undefined;
}

export function mimeFromPath(filePath) {
  return MIME_BY_EXTENSION.get(path.extname(filePath).toLowerCase());
}

export function resolveMime(filePath, firstBytes, suppliedType) {
  if (suppliedType) return suppliedType.toLowerCase();
  return sniffMime(firstBytes) || mimeFromPath(filePath) || "application/octet-stream";
}
