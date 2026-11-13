import { useState } from "react";
import type { YearInReviewGame, YearInReviewSettingsPatch, YearInReviewSummary } from "../../../../../shared/types";
import { parseYoutubeLink } from "../../../../../shared/youtubeLink";
import { Button } from "../../ui/Button";
import { GameTiles } from "./GameShelf";
import { Cover, formatRating, OpenGameButton, plural } from "./parts";
import { Crown } from "./RealmScenes";

export function GotyChapter({ summary, saveSettings, onPlayTheme, onStopTheme, themePlaying }: {
  summary: YearInReviewSummary;
  saveSettings: (patch: YearInReviewSettingsPatch) => Promise<string | null>;
  onPlayTheme: () => void;
  onStopTheme: () => void;
  themePlaying: boolean;
}) {
  const [panel, setPanel] = useState<"none" | "music" | "picker">("none");
  const goty = summary.goty;
  if (!goty) return null;
  const { game } = goty;
  const rest = summary.games.filter(item => item.id !== game.id);

  // The game's art is the whole window behind this (RealmScenes); the chapter is the words over it.
  return (
    <>
      <section className="yir-goty">
        <div className="yir-goty__text">
          <Crown />
          <p className="yir-goty__eyebrow">{goty.isLatestFinish ? "Your last finish of the year" : goty.isOverride ? "Your Game of the Year · your pick" : "Your Game of the Year"}</p>
          <h3 className="yir-goty__title">{game.title}</h3>
          <p className="yir-goty__meta">
            {game.ratingScore !== null && <span className="yir-goty__rating">{formatRating(game.ratingScore)}<small>/10</small></span>}
            <span>{[game.userPlatform, game.finishLabel].filter(Boolean).join(" · ")}</span>
          </p>
          {goty.note && <blockquote className="yir-goty__note">“{goty.note}”</blockquote>}
          <div className="yir-goty__actions">
            {goty.musicVideoId && (themePlaying
                ? <Button variant="primary" onClick={onStopTheme}>■ Stop theme</Button>
                : <Button variant="primary" onClick={onPlayTheme}>▶ Play theme</Button>)}
            <Button variant="outline" onClick={() => setPanel(panel === "music" ? "none" : "music")}>{goty.musicVideoId ? "Change theme music" : "Set theme music"}</Button>
            <Button variant="outline" onClick={() => setPanel(panel === "picker" ? "none" : "picker")}>Choose my GOTY</Button>
          </div>
        </div>
        <GotyCover game={game} />
      </section>
      {panel === "music" && <MusicForm hasMusic={Boolean(goty.musicVideoId)} saveSettings={saveSettings} onDone={() => setPanel("none")} />}
      {panel === "picker" && <GotyPicker summary={summary} saveSettings={saveSettings} onDone={() => setPanel("none")} />}
      {rest.length > 0 && (
        <section className="yir-covers" aria-label="The rest of your year">
          <h3 className="yir-covers__title">The rest of your year · {plural(rest.length, "game")}</h3>
          <GameTiles games={rest} large label="The rest of your year" />
        </section>
      )}
    </>
  );
}

// The GOTY's cover beside its name; opens the game's page when the stage allows it.
function GotyCover({ game }: { game: YearInReviewGame }) {
  return <OpenGameButton game={game} className="yir-goty__cover" fallbackClassName="yir-goty__cover"><Cover game={game} size="large" /></OpenGameButton>;
}

function MusicForm({ hasMusic, saveSettings, onDone }: { hasMusic: boolean; saveSettings: (patch: YearInReviewSettingsPatch) => Promise<string | null>; onDone: () => void }) {
  const [link, setLink] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const videoId = parseYoutubeLink(link);

  const save = async (musicLink: string | null) => {
    setSaving(true);
    const failure = await saveSettings({ musicLink });
    setSaving(false);
    if (failure) setError(failure);
    else onDone();
  };

  return (
    <form className="yir-form" data-yir-keys="off" onSubmit={event => { event.preventDefault(); if (videoId) void save(link); }}>
      <label className="field">
        <span className="field__label">YouTube link for the theme music</span>
        <input aria-label="YouTube link" value={link} placeholder="https://www.youtube.com/watch?v=…" onChange={event => { setLink(event.target.value); setError(null); }} />
      </label>
      <p className="yir-form__hint">{error ?? (link.trim() && !videoId ? "That isn't a YouTube video link." : "Only the video id is saved. It plays only when you press Play.")}</p>
      <div className="yir-form__actions">
        <Button variant="primary" type="submit" disabled={!videoId || saving}>Save music</Button>
        {hasMusic && <Button variant="outline" onClick={() => void save(null)} disabled={saving}>Remove</Button>}
        <Button variant="outline" onClick={onDone}>Cancel</Button>
      </div>
    </form>
  );
}

function GotyPicker({ summary, saveSettings, onDone }: { summary: YearInReviewSummary; saveSettings: (patch: YearInReviewSettingsPatch) => Promise<string | null>; onDone: () => void }) {
  const [error, setError] = useState<string | null>(null);
  const choose = async (gotyCompletedId: string | null) => {
    const failure = await saveSettings({ gotyCompletedId });
    if (failure) setError(failure);
    else onDone();
  };
  return (
    <div className="yir-form" data-yir-keys="off">
      <div className="yir-form__head">
        <span className="field__label">Choose your Game of the Year</span>
        <div className="yir-form__actions">
          {summary.goty?.isOverride && <Button small variant="outline" onClick={() => void choose(null)}>Use automatic pick</Button>}
          <Button small variant="outline" onClick={onDone}>Cancel</Button>
        </div>
      </div>
      {error && <p className="yir-form__hint">{error}</p>}
      <ul className="yir-picker" aria-label="Games finished this year">
        {summary.games.map(game => (
          <li key={game.id}>
            <button type="button" className={game.id === summary.goty?.game.id ? "active" : ""} onClick={() => void choose(game.id)}>
              <Cover game={game} />
              <span className="yir-game__text">
                <b>{game.title}</b>
                <small>{[game.ratingScore !== null ? `${formatRating(game.ratingScore)}/10` : "Not rated", game.finishLabel].join(" · ")}</small>
              </span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
