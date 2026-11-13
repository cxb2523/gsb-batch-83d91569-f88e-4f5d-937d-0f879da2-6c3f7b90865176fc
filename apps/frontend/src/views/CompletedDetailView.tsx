import { CoverScene } from "../ui/CoverScene";
import { FramedPanel } from "../ui/FramedPanel";
import { Fragment, useEffect, useState } from "react";
import type { CompletedGameDetail } from "../../../../shared/types";
import type { CompletedGameDetailWorkflow } from "../useCompletedGameDetailWorkflow";
import { formatCompletedDateLabel } from "./completedPresentation";
import { cachedCoverSrc, igdbCoverSrc, screenshotSrc } from "../artwork";

export function CompletedDetailView({ apiBaseUrl, workflow, onBack, backLabel = "library" }: { apiBaseUrl: string; workflow: CompletedGameDetailWorkflow; onBack: () => void; backLabel?: string }) {
  const { detail, matchCandidates, matchMessage, appliedMatchIgdbId } = workflow;
  const {
    deleteCurrent: onDelete,
    loadMatchCandidates: onFixMatch,
    saveMatch: onSaveMatch,
    renameCompletedGame: onRename,
    editCompletedDetails: onEditDetails
  } = workflow.actions;
  const [editingTitle, setEditingTitle] = useState(false);
  const [titleDraft, setTitleDraft] = useState("");
  const [editingFields, setEditingFields] = useState(false);
  const [fieldDraft, setFieldDraft] = useState<Record<string, string>>({});
  if (!detail) return <section className="detail-view"><button type="button" className="secondary inline" onClick={onBack}>Back</button><div className="state">Loading completed game...</div></section>;
  const screenshots = detail.screenshots.slice(0, 6);
  const completedLabel = formatCompletedDateLabel(detail.completionDate, detail.completionMonth, detail.completionYear);
  const startTitleEdit = () => { setTitleDraft(detail.title); setEditingTitle(true); };
  const saveTitleEdit = () => { setEditingTitle(false); if (titleDraft.trim() && titleDraft.trim() !== detail.title) onRename(titleDraft.trim()); };
  const cancelTitleEdit = () => { setEditingTitle(false); setTitleDraft(""); };

  const startFieldEdit = () => {
    setFieldDraft({
      userPlatform: detail.userPlatform ?? "",
      ratingRaw: detail.ratingRaw ?? "",
      completionDate: detail.completionDate ?? "",
      completionMonth: detail.completionMonth ?? "",
      completionYear: String(detail.completionYear ?? ""),
      completionPrecision: detail.completionPrecision ?? "none",
      developer: detail.developer ?? "",
      publisher: detail.publisher ?? "",
      notes: detail.notes ?? ""
    });
    setEditingFields(true);
  };
  const saveFieldEdit = () => {
    setEditingFields(false);
    const patch: Record<string, unknown> = {};
    if (fieldDraft.userPlatform !== (detail.userPlatform ?? "")) patch.userPlatform = fieldDraft.userPlatform || null;
    if (fieldDraft.ratingRaw !== (detail.ratingRaw ?? "")) patch.ratingRaw = fieldDraft.ratingRaw || null;
    if (fieldDraft.completionDate !== (detail.completionDate ?? "")) patch.completionDate = fieldDraft.completionDate || null;
    if (fieldDraft.completionMonth !== (detail.completionMonth ?? "")) patch.completionMonth = fieldDraft.completionMonth || null;
    if (fieldDraft.completionYear !== String(detail.completionYear ?? "")) patch.completionYear = fieldDraft.completionYear ? Number(fieldDraft.completionYear) : null;
    if (fieldDraft.completionPrecision !== (detail.completionPrecision ?? "none")) patch.completionPrecision = fieldDraft.completionPrecision;
    if (fieldDraft.developer !== (detail.developer ?? "")) patch.developer = fieldDraft.developer || null;
    if (fieldDraft.publisher !== (detail.publisher ?? "")) patch.publisher = fieldDraft.publisher || null;
    if (fieldDraft.notes !== (detail.notes ?? "")) patch.notes = fieldDraft.notes || null;
    if (Object.keys(patch).length > 0) onEditDetails(patch);
  };
  const cancelFieldEdit = () => { setEditingFields(false); setFieldDraft({}); };

  return (
    <CoverScene coverSrc={detail.coverImageId ? cachedCoverSrc(detail.coverImageId, apiBaseUrl) : screenshots[0] ? screenshotSrc(screenshots[0].imageId) : undefined}>
      <div className="detail-view completed-detail-view">
        <FramedPanel className="detail-fields"><div className="detail-fields__scroll">
          <button type="button" className="secondary inline" onClick={onBack}>← back to {backLabel}</button>
          <p className="journal-date-subtitle">Finished {completedLabel}</p>
        {editingTitle ? (
          <div className="inline-edit-row">
            <input className="inline-edit-input" value={titleDraft} onChange={event => setTitleDraft(event.target.value)} onKeyDown={event => { if (event.key === "Enter") saveTitleEdit(); if (event.key === "Escape") cancelTitleEdit(); }} autoFocus />
            <button type="button" className="action-sync inline-edit-btn" onClick={saveTitleEdit}>Save</button>
            <button type="button" className="secondary inline-edit-btn" onClick={cancelTitleEdit}>Cancel</button>
          </div>
        ) : (
          <div className="inline-title-row">
            <h2>{detail.title}</h2>
            <button type="button" className="secondary inline edit-title-btn" onClick={startTitleEdit}>Edit title</button>
          </div>
        )}
          <hr className="entry-divider" />
          <div className={`match-status ${detail.matchStatus}`}>{detail.matchStatus === "needsReview" ? "IGDB match needs review" : detail.igdbId ? `IGDB #${detail.igdbId}` : "No IGDB match yet"}</div>
          {editingFields ? (
            <div className="field-edit-form">
              <label>Platform<input value={fieldDraft.userPlatform ?? ""} onChange={event => setFieldDraft(d => ({ ...d, userPlatform: event.target.value }))} placeholder="PC, PS5, Switch..." /></label>
              <label>Rating<input value={fieldDraft.ratingRaw ?? ""} onChange={event => setFieldDraft(d => ({ ...d, ratingRaw: event.target.value }))} placeholder="9/10" /></label>
              <label>Completion date<input value={fieldDraft.completionDate ?? ""} onChange={event => setFieldDraft(d => ({ ...d, completionDate: event.target.value }))} placeholder="DD MM YYYY" /></label>
              <label>Completion month<input value={fieldDraft.completionMonth ?? ""} onChange={event => setFieldDraft(d => ({ ...d, completionMonth: event.target.value }))} placeholder="YYYY-MM" /></label>
              <label>Completion year<input value={fieldDraft.completionYear ?? ""} onChange={event => setFieldDraft(d => ({ ...d, completionYear: event.target.value }))} placeholder="2024" /></label>
              <label>Completion precision<select value={fieldDraft.completionPrecision ?? "none"} onChange={event => setFieldDraft(d => ({ ...d, completionPrecision: event.target.value }))}><option value="exact">Exact</option><option value="month">Month</option><option value="year">Year</option><option value="none">None</option></select></label>
              <label>Developer<input value={fieldDraft.developer ?? ""} onChange={event => setFieldDraft(d => ({ ...d, developer: event.target.value }))} /></label>
              <label>Publisher<input value={fieldDraft.publisher ?? ""} onChange={event => setFieldDraft(d => ({ ...d, publisher: event.target.value }))} /></label>
              <label className="wide-field">Notes<textarea value={fieldDraft.notes ?? ""} onChange={event => setFieldDraft(d => ({ ...d, notes: event.target.value }))} /></label>
              <div className="settings-actions">
                <button type="button" className="action-sync" onClick={saveFieldEdit}>Save changes</button>
                <button type="button" className="secondary" onClick={cancelFieldEdit}>Cancel</button>
              </div>
            </div>
          ) : (
            <>
              <div className="ruled">
                <dl>
                  <dt>Your platform</dt><dd>{detail.userPlatform || "-"}</dd>
                  <dt>Rating</dt><dd>{detail.ratingRaw || "-"}</dd>
                  <dt>Completed</dt><dd>{completedLabel}</dd>
                  <dt>Developer</dt><dd>{detail.developer ?? detail.igdbDeveloper ?? "-"}</dd>
                  <dt>Publisher</dt><dd>{detail.publisher ?? detail.igdbPublisher ?? "-"}</dd>
                  <dt>Genres</dt><dd>{(detail.genres.length ? detail.genres : detail.igdbGenres).join(", ") || "-"}</dd>
                  <dt>Platforms</dt><dd>{(detail.platforms.length ? detail.platforms : detail.igdbPlatforms).join(", ") || "-"}</dd>
                  <dt>IGDB date</dt><dd>{detail.igdbReleaseDate ?? "-"}</dd>
                </dl>
              </div>
              {detail.summary && <p className="summary-block">{detail.summary}</p>}
              {detail.notes && <div className="personal-note">{detail.notes}</div>}
              {Object.keys(detail.extra).length > 0 && (
                <div className="extra-fields">
                  <h3>Extra fields</h3>
                  <dl>{Object.entries(detail.extra).map(([key, value]) => <Fragment key={key}><dt>{key}</dt><dd>{value}</dd></Fragment>)}</dl>
                </div>
              )}
              <div className="settings-actions" style={{ marginTop: "16px" }}>
                <button type="button" className="secondary" onClick={startFieldEdit}>Edit details</button>
                <button type="button" className="secondary" onClick={onFixMatch}>Fix match</button>
                <button type="button" className="secondary" onClick={onFixMatch}>Refresh IGDB</button>
                <button type="button" className="danger" onClick={onDelete}>Delete</button>
              </div>
            </>
          )}
          {matchMessage && <div className="state compact">{matchMessage}</div>}
          {matchCandidates.length > 0 && (
            <div className="match-candidates">
              <h3>IGDB match candidates</h3>
              {matchCandidates.map(candidate => (
                <article className={`match-candidate${candidate.igdbId === appliedMatchIgdbId ? " applied" : ""}`} key={candidate.igdbId}>
                  {candidate.coverImageId && <img alt="" src={igdbCoverSrc(candidate.coverImageId)} />}
                  <div>
                    <strong>{candidate.title}</strong>
                    <span>{candidate.releaseDate ?? "Date unknown"} - {candidate.platforms.join(", ") || "Platforms unknown"} - {Math.round(candidate.confidence)}%</span>
                    {candidate.summary && <p>{candidate.summary}</p>}
                  </div>
                  {candidate.igdbId === appliedMatchIgdbId
                    ? <span className="applied-badge">Applied</span>
                    : <button type="button" className="action-sync" onClick={() => onSaveMatch(candidate.igdbId)}>Use match</button>}
                </article>
              ))}
            </div>
          )}
        </div></FramedPanel>
        <FramedPanel className="detail-media"><CompletedMediaGallery screenshots={screenshots} /></FramedPanel>
      </div>
    </CoverScene>
  );
}


type CompletedMediaItem = { key: string; label: string; src: string; thumbSrc: string; fit: "cover"; kind: "screenshot" };

function CompletedMediaGallery({
  screenshots
}: {
  screenshots: CompletedGameDetail["screenshots"];
}) {
  const items: CompletedMediaItem[] = [
    ...screenshots.map((screen, index) => ({
      key: `screenshot-${screen.imageId}`,
      label: `Screenshot ${index + 1}`,
      src: screenshotSrc(screen.imageId, "hero"),
      thumbSrc: screenshotSrc(screen.imageId),
      fit: "cover" as const,
      kind: "screenshot" as const
    }))
  ];
  const [selectedIndex, setSelectedIndex] = useState(0);
  useEffect(() => {
    setSelectedIndex(0);
  }, [items.map(item => item.key).join("|")]);
  if (items.length === 0) {
    return (
      <div className="completed-media-gallery" aria-label="Completed game media">
        <div className="completed-media-hero kind-screenshot">
          <span className="placeholder">No IGDB screenshots yet</span>
        </div>
        <div className="state compact">No IGDB screenshots saved yet.</div>
      </div>
    );
  }
  const selected = items[Math.min(selectedIndex, items.length - 1)];
  const move = (direction: -1 | 1) => {
    setSelectedIndex(current => Math.max(0, Math.min(items.length - 1, current + direction)));
  };
  return (
    <div
      className="completed-media-gallery"
      tabIndex={0}
      onKeyDown={event => {
        if (event.key === "ArrowLeft") move(-1);
        if (event.key === "ArrowRight") move(1);
      }}
      aria-label="Completed game media"
    >
      <div className={`completed-media-hero kind-${selected.kind} journal-hero`}>
        <img alt="" className={selected.fit} src={selected.src} />
      </div>
      <div className="thumb-strip completed-media-thumbs journal-thumbs">
        {items.map((item, index) => (
          <button
            type="button"
            className={index === selectedIndex ? "active" : ""}
            key={item.key}
            onClick={() => setSelectedIndex(index)}
          >
            <span className="sr-only">{item.label}</span>
            <img alt="" className={item.fit} src={item.thumbSrc} />
          </button>
        ))}
      </div>
    </div>
  );
}
