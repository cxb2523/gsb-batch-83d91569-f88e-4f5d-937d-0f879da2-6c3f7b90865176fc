import { artworkSrc, cachedCoverSrc } from "../artwork";
import { CoverScene } from "../ui/CoverScene";
import { FramedPanel } from "../ui/FramedPanel";
import { WatchButton } from "../ui/WatchButton";
import { changeDay, dateChangeLabel } from "../ui/dateChange";
import type { ReleaseDetailWorkflow } from "../useReleaseDetailWorkflow";
import { ReleaseFieldsPanel, ReleaseTitleEditor } from "./ReleaseDetailEditors";
import { ReleaseMediaGallery } from "./ReleaseMediaGallery";

export function DetailView({ apiBaseUrl, workflow, onBack }: { apiBaseUrl: string; workflow: ReleaseDetailWorkflow; onBack: () => void }) {
  const { detail, actions } = workflow;
  const onDelete = () => void actions.deleteCurrent("delete");
  const onDeleteBlocked = () => void actions.deleteCurrent("delete-block");
  const {
    uploadArtwork: onUploadArtwork,
    removeHeroArtwork: onRemoveArtwork,
    promoteNextArtwork: onPromoteArtwork,
    renameRelease: onRename,
    editReleaseDetails: onEditDetails
  } = actions;
  if (!detail) {
    return (
      <section className="detail-view">
        <button type="button" className="secondary inline" onClick={onBack}>Back</button>
        <div className="state">Loading details...</div>
      </section>
    );
  }

  // The IGDB cover first; else the user's own artwork, then any hero image (shown, but not tinted from).
  const cover = detail.artworks.find(a => a.source === "cover")
    ?? detail.artworks.find(a => a.source === "local")
    ?? detail.artworks.find(a => a.source === "artwork" || a.source === "steamgriddb");
  const coverSrc = !cover ? undefined : cover.source === "cover" ? cachedCoverSrc(cover.imageId, apiBaseUrl) : artworkSrc(cover, "detail", apiBaseUrl);
  return (
    <CoverScene coverSrc={coverSrc}>
      <div className="detail-view">
        <FramedPanel className="detail-fields">
          <div className="detail-fields__scroll">
            <button type="button" className="secondary inline" onClick={onBack}>← Back</button>
            <ReleaseTitleEditor detail={detail} onRename={onRename} />
            <div className="detail-title-actions">
              <p className="journal-date-subtitle">{detail.category} · {detail.dateText}</p>
              <WatchButton small watched={Boolean(detail.watched)} onChange={watched => void actions.setWatched(watched)} />
            </div>
            <hr className="entry-divider" />
            <ReleaseFieldsPanel detail={detail} onEditDetails={onEditDetails} />
            {detail.dateChanges && detail.dateChanges.length > 0 && (
              <section className="date-history" aria-label="Date history">
                <h3>Date history</h3>
                <ul>{detail.dateChanges.map((change, index) => <li key={index} className={`date-badge--${change.kind}`}><span>{dateChangeLabel(change)} to {change.toText}</span><small>{changeDay(change.changedAt)}</small></li>)}</ul>
              </section>
            )}
            {detail.igdbUrl && <a className="external" href={detail.igdbUrl}>Open IGDB →</a>}
            <div className="danger-actions">
              <button type="button" className="danger" onClick={onDelete}>Delete</button>
              <button type="button" className="danger secondary" onClick={onDeleteBlocked}>Delete + block</button>
            </div>
          </div>
        </FramedPanel>
        <FramedPanel className="detail-media">
          <ReleaseMediaGallery screenshots={detail.screenshots} trailers={detail.trailers} />
          <div className="artwork-actions">
            <label className="file-button">Add artwork<input type="file" accept="image/png,image/jpeg,image/webp" onChange={event => onUploadArtwork(event.target.files?.[0] ?? null)} /></label>
            <button type="button" className="secondary" onClick={onRemoveArtwork}>Remove artwork</button>
            <button type="button" className="secondary" onClick={onPromoteArtwork}>Move next to hero</button>
          </div>
        </FramedPanel>
      </div>
    </CoverScene>
  );
}
