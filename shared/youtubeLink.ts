const VIDEO_ID = /^[A-Za-z0-9_-]{11}$/;
const HOSTS = new Set(["youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com", "youtube-nocookie.com", "www.youtube-nocookie.com"]);

// The YouTube video id in a pasted link or bare id, or null. Only the id is ever stored or embedded,
// so anything that isn't a plain YouTube video link (other hosts, playlists, junk) is refused.
export function parseYoutubeLink(text: string): string | null {
  const input = text.trim();
  if (VIDEO_ID.test(input)) return input;
  let url: URL;
  try {
    url = new URL(/^[a-z][a-z0-9+.-]*:/i.test(input) ? input : `https://${input}`);
  } catch {
    return null;
  }
  if (url.protocol !== "https:" && url.protocol !== "http:") return null;
  const host = url.hostname.toLowerCase();
  const [first, second] = url.pathname.split("/").filter(Boolean);
  let id: string | null | undefined;
  if (host === "youtu.be") id = first;
  else if (HOSTS.has(host)) id = first === "watch" ? url.searchParams.get("v") : first === "embed" || first === "shorts" ? second : null;
  return id && VIDEO_ID.test(id) ? id : null;
}
