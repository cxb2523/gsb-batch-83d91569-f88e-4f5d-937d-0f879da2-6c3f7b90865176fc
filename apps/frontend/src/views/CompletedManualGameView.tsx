import { igdbCoverSrc } from "../artwork";
import { FramedPanel } from "../ui/FramedPanel";
import type { CompletedGameMatchCandidate } from "../../../../shared/types";
import type { ManualAddWorkflow } from "../candidateSearch";
import type { ManualCompletedGameForm } from "../useCompletedManualGameWorkflow";

export function CompletedManualGameView({ manual, onBack }: { manual: ManualAddWorkflow<ManualCompletedGameForm, CompletedGameMatchCandidate>; onBack: () => void }) {
  const { form: manualGame, candidates, searchStatus, searchMessage } = manual;
  const { setForm: onChange, save: onSave, search: onSearchIgdb, useCandidate: onUseCandidate } = manual.actions;
  const updateField = (key: keyof ManualCompletedGameForm, value: string) => {
    onChange(current => ({ ...current, [key]: value }));
  };

  return (
    <>
    <FramedPanel className="manual-view"><form className="manual-view__form" onSubmit={event => { event.preventDefault(); onSave({ ...manualGame, title: manualGame.title.trim(), userPlatform: manualGame.userPlatform.trim(), ratingRaw: manualGame.ratingRaw.trim(), completionDate: manualGame.completionDate.trim(), notes: manualGame.notes.trim() }); }}>
      <button type="button" className="secondary inline" onClick={onBack}>← back</button>
      <div>
        <p className="kicker">A finished game</p>
        <h2>Add completed game</h2>
      </div>
      <hr className="entry-divider" />
      <div className="manual-grid">
        <label>Title<input aria-label="Completed game title" value={manualGame.title} onInput={event => updateField("title", event.currentTarget.value)} /></label>
        <label>Platform<input aria-label="Completed game platform" value={manualGame.userPlatform} onInput={event => updateField("userPlatform", event.currentTarget.value)} placeholder="PC, PS5, Switch..." /></label>
        <label>Rating<input aria-label="Completed game rating" value={manualGame.ratingRaw} onInput={event => updateField("ratingRaw", event.currentTarget.value)} placeholder="9/10" /></label>
        <label>Completion date<input aria-label="Completed game completion date" value={manualGame.completionDate} onInput={event => updateField("completionDate", event.currentTarget.value)} placeholder="DD MM YYYY" /></label>
        <label className="wide-field">Notes<textarea aria-label="Completed game notes" value={manualGame.notes} onInput={event => updateField("notes", event.currentTarget.value)} /></label>
      </div>
      <div className="settings-actions">
        <button type="button" className="secondary" onClick={() => void onSearchIgdb()} disabled={searchStatus === "searching"}>{searchStatus === "searching" ? "Searching..." : "Search IGDB"}</button>
        <button type="submit">Save completed game</button>
      </div>
      {searchMessage && <div className={`state ${searchStatus === "error" ? "error" : ""}`}>{searchMessage}</div>}
    </form></FramedPanel>
    <FramedPanel className="manual-candidates-panel">
      <h2>IGDB matches</h2>
      {candidates.length > 0 && (
        <div className="manual-candidates">
          {candidates.map(candidate => (
            <button type="button" className="manual-candidate" key={candidate.igdbId} onClick={() => onUseCandidate(candidate)}>
              {candidate.coverImageId && <img src={igdbCoverSrc(candidate.coverImageId, "small")} alt="" loading="lazy" />}
              <span>
                <strong>{candidate.title}</strong>
                <small>{candidate.releaseDate ?? "Release date unavailable"} - {candidate.platforms.slice(0, 4).join(", ") || "No platforms"}</small>
              </span>
            </button>
          ))}
        </div>
      )}
    </FramedPanel>
    </>
  );
}
