import { Button } from "./Button";

// Watch or stop watching a release. Watched games are the ones the app tells you about: release day and
// date changes.
export function WatchButton({ watched, onChange, small = false }: { watched: boolean; onChange: (watched: boolean) => void; small?: boolean }) {
  return (
    <Button small={small} className={`watch-button${watched ? " watch-button--on" : ""}`} aria-pressed={watched} onClick={() => onChange(!watched)}>
      {watched ? "★ Watching" : "☆ Watch"}
    </Button>
  );
}
