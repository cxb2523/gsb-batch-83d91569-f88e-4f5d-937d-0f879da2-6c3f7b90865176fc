// The one place that knows how the app embeds YouTube: the privacy-enhanced nocookie host, the
// player parameters, and the page origin YouTube wants for the embed. Used by the trailer gallery
// and the Year in Review theme player.
export function youtubePosterSrc(videoId: string) {
  return `https://i.ytimg.com/vi/${encodeURIComponent(videoId)}/hqdefault.jpg`;
}

export function youtubeEmbedSrc(videoId: string) {
  const params = new URLSearchParams({ autoplay: "1", playsinline: "1", rel: "0" });
  const origin = globalThis.location?.origin;
  if (origin && /^https?:\/\//.test(origin)) params.set("origin", origin);
  return `https://www.youtube-nocookie.com/embed/${encodeURIComponent(videoId)}?${params.toString()}`;
}
