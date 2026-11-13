import { useEffect, useState } from "react";
import type { GameTrailer, ReleaseArtwork } from "../../../../shared/types";
import { screenshotSrc } from "../artwork";
import { youtubeEmbedSrc, youtubePosterSrc } from "../youtube";

type GalleryItem =
  | { kind: "trailer"; key: string; label: string; videoId: string; name?: string | null; heroSrc: string; thumbSrc: string }
  | { kind: "screenshot"; key: string; label: string; heroSrc: string; thumbSrc: string };

export function ReleaseMediaGallery({ screenshots, trailers }: { screenshots: ReleaseArtwork[]; trailers?: GameTrailer[] }) {
  const trailerItems: GalleryItem[] = (trailers ?? []).slice(0, 1).map(trailer => ({
    kind: "trailer",
    key: `trailer-${trailer.videoId}`,
    label: trailer.name || "Trailer",
    videoId: trailer.videoId,
    name: trailer.name,
    heroSrc: youtubePosterSrc(trailer.videoId),
    thumbSrc: youtubePosterSrc(trailer.videoId)
  }));
  const screenshotItems: GalleryItem[] = (screenshots ?? []).slice(0, 6).map((screen, index) => ({
    kind: "screenshot",
    key: `screenshot-${screen.imageId}`,
    label: `Screenshot ${index + 1}`,
    heroSrc: screenshotSrc(screen.imageId, "hero"),
    thumbSrc: screenshotSrc(screen.imageId, "thumb")
  }));
  const items = [...trailerItems, ...screenshotItems];
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [playingKey, setPlayingKey] = useState<string | null>(null);
  const [overlayOpen, setOverlayOpen] = useState(false);

  useEffect(() => {
    setSelectedIndex(0);
    setPlayingKey(null);
    setOverlayOpen(false);
  }, [items.map(item => item.key).join("|")]);

  if (items.length === 0) {
    return (
      <div className="upcoming-media-gallery completed-media-gallery" aria-label="Release media">
        <div className="upcoming-media-hero completed-media-hero kind-screenshot journal-hero">
          <span className="placeholder">No IGDB screenshots yet</span>
        </div>
        <div className="state compact">No IGDB screenshots saved yet.</div>
      </div>
    );
  }

  const selected = items[Math.min(selectedIndex, items.length - 1)];
  const move = (direction: -1 | 1) => {
    setPlayingKey(null);
    setSelectedIndex(current => Math.max(0, Math.min(items.length - 1, current + direction)));
  };
  const openOverlay = () => {
    setPlayingKey(null);
    setOverlayOpen(true);
  };
  const closeOverlay = () => {
    setOverlayOpen(false);
    setPlayingKey(null);
  };

  return (
    <>
      <div
        className="upcoming-media-gallery completed-media-gallery"
        tabIndex={0}
        onKeyDown={event => {
          if (event.key === "ArrowLeft") move(-1);
          if (event.key === "ArrowRight") move(1);
          if (event.key === "Home") { setPlayingKey(null); setSelectedIndex(0); }
          if (event.key === "End") { setPlayingKey(null); setSelectedIndex(items.length - 1); }
        }}
        aria-label="Release media"
      >
        <div className={`upcoming-media-hero completed-media-hero kind-${selected.kind} journal-hero`}>
          <MediaHero item={selected} playingKey={playingKey} onPlay={() => setPlayingKey(selected.key)} hidePlayButton={overlayOpen} />
          <button type="button" className="upcoming-media-fullscreen secondary" onClick={openOverlay}>Open fullscreen</button>
        </div>
        <div className="upcoming-media-thumbs thumb-strip completed-media-thumbs journal-thumbs">
          {items.map((item, index) => (
            <button
              type="button"
              className={index === selectedIndex ? "active" : ""}
              key={item.key}
              onClick={() => {
                setSelectedIndex(index);
                setPlayingKey(null);
              }}
            >
              <span className="sr-only">{item.kind === "trailer" ? `Trailer: ${item.label}` : item.label}</span>
              <img alt="" className="cover" src={item.thumbSrc} />
              {item.kind === "trailer" && <span aria-hidden="true" className="trailer-thumb-label">Trailer</span>}
            </button>
          ))}
        </div>
      </div>
      {overlayOpen && (
        <div
          className="upcoming-media-overlay"
          tabIndex={0}
          role="dialog"
          aria-modal="true"
          aria-label="Fullscreen release media"
          onKeyDown={event => {
            if (event.key === "Escape") closeOverlay();
            if (event.key === "ArrowLeft") move(-1);
            if (event.key === "ArrowRight") move(1);
          }}
        >
          <button type="button" className="upcoming-media-close secondary" onClick={closeOverlay}>Close</button>
          <div className="upcoming-media-overlay-frame">
            <MediaHero item={selected} playingKey={playingKey} onPlay={() => setPlayingKey(selected.key)} />
          </div>
        </div>
      )}
    </>
  );
}

function MediaHero({ item, playingKey, onPlay, hidePlayButton = false }: { item: GalleryItem; playingKey: string | null; onPlay: () => void; hidePlayButton?: boolean }) {
  if (item.kind === "trailer") {
    if (playingKey === item.key) {
      return (
        <iframe
          title={item.label}
          src={youtubeEmbedSrc(item.videoId)}
          allow="fullscreen; autoplay; encrypted-media; picture-in-picture"
          allowFullScreen
        />
      );
    }
    return (
      <div className="upcoming-trailer-poster">
        <img alt="" className="cover" src={item.heroSrc} />
        {!hidePlayButton && <button type="button" className="trailer-play-button" onClick={onPlay}>Play trailer</button>}
        <div className="upcoming-trailer-copy">
          <span>{item.label}</span>
        </div>
      </div>
    );
  }
  return <img alt="" className="cover" src={item.heroSrc} />;
}
