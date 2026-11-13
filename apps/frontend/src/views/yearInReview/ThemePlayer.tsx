import { youtubeEmbedSrc } from "../../youtube";

// The theme plays in the background: the YouTube player is loaded but invisible (still in the window, so the
// browser keeps it playing), and a small pill says what is playing with a Stop button.
export function ThemePlayer({ videoId, onStop }: { videoId: string; onStop: () => void }) {
  return (
    <aside className="yir-player" aria-label="Theme music">
      <iframe className="yir-player__frame" title="Theme music" src={youtubeEmbedSrc(videoId)} allow="autoplay; encrypted-media" tabIndex={-1} aria-hidden="true" />
      <span className="yir-player__note" aria-hidden="true"><i /><i /><i /></span>
      <span className="yir-player__label">Theme music</span>
      <button type="button" className="yir-player__stop" onClick={onStop}>Stop</button>
    </aside>
  );
}
