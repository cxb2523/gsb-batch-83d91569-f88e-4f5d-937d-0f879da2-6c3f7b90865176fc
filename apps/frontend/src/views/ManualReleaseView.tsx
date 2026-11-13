import { igdbCoverSrc } from "../artwork";
import { FramedPanel } from "../ui/FramedPanel";
import type { ManualReleaseCandidate } from "../../../../shared/types";
import type { ManualAddWorkflow } from "../candidateSearch";

export interface ManualGameForm {
  igdbId?: number;
  title: string;
  publishers: string;
  developers: string;
  platforms: string;
  category: string;
  dateText: string;
  datePrecision: string;
  releaseDate: string;
  releaseWindow: string;
  sourceUrl: string;
  artworks?: ManualReleaseCandidate["artworks"];
  screenshots?: ManualReleaseCandidate["screenshots"];
  trailers?: ManualReleaseCandidate["trailers"];
}

export function ManualReleaseView({ manual, onBack }: { manual: ManualAddWorkflow<ManualGameForm, ManualReleaseCandidate>; onBack: () => void }) {
  const { form: manualGame, candidates, searchStatus, searchMessage } = manual;
  const { setForm: onChange, save: onSave, search: onSearchIgdb, useCandidate: onUseCandidate } = manual.actions;
  const update = (key: keyof ManualGameForm, value: string) => onChange({ ...manualGame, [key]: value });
  return (
    <>
    <FramedPanel className="manual-view">
      <button type="button" className="secondary inline" onClick={onBack}>Back</button>
      <div>
        <p className="kicker">A new entry</p>
        <h2>Add manual game</h2>
      </div>
      <hr className="entry-divider" />
      <div className="manual-grid">
        <label>Title<input value={manualGame.title} onChange={event => update("title", event.target.value)} /></label>
        <label>Publishers<input value={manualGame.publishers} onChange={event => update("publishers", event.target.value)} /></label>
        <label>Developers<input value={manualGame.developers} onChange={event => update("developers", event.target.value)} /></label>
        <label>Platforms<input value={manualGame.platforms} onChange={event => update("platforms", event.target.value)} /></label>
        <label>Category<select value={manualGame.category} onChange={event => update("category", event.target.value)}><option>Main</option><option>DLC</option><option>Expansion</option><option>Standalone Expansion</option><option>Remake</option><option>Remaster</option><option>Expanded Game</option><option>Port</option></select></label>
        <label>Date text<input value={manualGame.dateText} onChange={event => update("dateText", event.target.value)} placeholder="Feb 20, 2027" /></label>
        <label>Date precision<select value={manualGame.datePrecision} onChange={event => update("datePrecision", event.target.value)}><option>Exact</option><option>Month</option><option>Window</option><option>Year</option><option>TBA</option></select></label>
        <label>Release date<input value={manualGame.releaseDate} onChange={event => update("releaseDate", event.target.value)} placeholder="2027-02-20" /></label>
        <label>Release window<input value={manualGame.releaseWindow} onChange={event => update("releaseWindow", event.target.value)} placeholder="Early 2027" /></label>
        <label>Source URL<input value={manualGame.sourceUrl} onChange={event => update("sourceUrl", event.target.value)} /></label>
      </div>
      <div className="manual-actions">
        <button type="button" className="secondary" onClick={() => void onSearchIgdb()} disabled={searchStatus === "searching"}>
          {searchStatus === "searching" ? "Searching..." : "Search IGDB"}
        </button>
        <button type="button" onClick={() => void onSave()}>Save game</button>
      </div>
      {searchMessage && <div className={`state ${searchStatus === "error" ? "error" : ""}`}>{searchMessage}</div>}
    </FramedPanel>
    <FramedPanel className="manual-candidates-panel">
      <h2>IGDB matches</h2>
      {candidates.length > 0 && (
        <div className="manual-candidates">
          {candidates.map(candidate => (
            <button type="button" className="manual-candidate" key={candidate.igdbId} onClick={() => onUseCandidate(candidate)}>
              {candidate.coverImageId && (
                <img
                  src={igdbCoverSrc(candidate.coverImageId, "small")}
                  alt=""
                  loading="lazy"
                />
              )}
              <span>
                <strong>{candidate.title}</strong>
                <small>{candidate.dateText} - {candidate.platforms.slice(0, 4).join(", ") || "No platforms"}</small>
              </span>
            </button>
          ))}
        </div>
      )}
    </FramedPanel>
    </>
  );
}
