import { useState } from "react";
import type { ReleaseDetail } from "../../../../shared/types";
import { buildReleaseEditPatch, createReleaseFieldDraft, type ReleaseEditPatch } from "../releaseEditing";

export function ReleaseTitleEditor({ detail, onRename }: { detail: ReleaseDetail; onRename: (title: string) => void }) {
  const [editingTitle, setEditingTitle] = useState(false);
  const [titleDraft, setTitleDraft] = useState("");

  const startTitleEdit = () => {
    setTitleDraft(detail.title);
    setEditingTitle(true);
  };
  const saveTitleEdit = () => {
    setEditingTitle(false);
    if (titleDraft.trim() && titleDraft.trim() !== detail.title) onRename(titleDraft.trim());
  };
  const cancelTitleEdit = () => {
    setEditingTitle(false);
    setTitleDraft("");
  };

  if (editingTitle) {
    return (
      <div className="inline-edit-row">
        <input
          className="inline-edit-input"
          value={titleDraft}
          onChange={event => setTitleDraft(event.target.value)}
          onKeyDown={event => {
            if (event.key === "Enter") saveTitleEdit();
            if (event.key === "Escape") cancelTitleEdit();
          }}
          autoFocus
        />
        <button type="button" className="action-sync inline-edit-btn" onClick={saveTitleEdit}>Save</button>
        <button type="button" className="secondary inline-edit-btn" onClick={cancelTitleEdit}>Cancel</button>
      </div>
    );
  }

  return (
    <div className="inline-title-row">
      <h2>{detail.title}</h2>
      <button type="button" className="secondary inline edit-title-btn" onClick={startTitleEdit}>Edit title</button>
    </div>
  );
}

export function ReleaseFieldsPanel({ detail, onEditDetails }: { detail: ReleaseDetail; onEditDetails: (patch: ReleaseEditPatch) => void }) {
  const [editingFields, setEditingFields] = useState(false);
  const [fieldDraft, setFieldDraft] = useState<ReleaseEditPatch>({});

  const startFieldEdit = () => {
    setFieldDraft(createReleaseFieldDraft(detail));
    setEditingFields(true);
  };
  const saveFieldEdit = () => {
    setEditingFields(false);
    const patch = buildReleaseEditPatch(detail, fieldDraft);
    if (Object.keys(patch).length > 0) onEditDetails(patch);
  };
  const cancelFieldEdit = () => {
    setEditingFields(false);
    setFieldDraft({});
  };

  if (editingFields) {
    return (
      <div className="field-edit-form">
        <label>Publishers<input value={fieldDraft.publishers ?? ""} onChange={event => setFieldDraft(d => ({ ...d, publishers: event.target.value }))} /></label>
        <label>Developers<input value={fieldDraft.developers ?? ""} onChange={event => setFieldDraft(d => ({ ...d, developers: event.target.value }))} /></label>
        <label>Platforms<input value={fieldDraft.platforms ?? ""} onChange={event => setFieldDraft(d => ({ ...d, platforms: event.target.value }))} /></label>
        <label>Category<select value={fieldDraft.category ?? "Main"} onChange={event => setFieldDraft(d => ({ ...d, category: event.target.value }))}><option>Main</option><option>DLC</option><option>Expansion</option><option>Standalone Expansion</option><option>Remake</option><option>Remaster</option><option>Expanded Game</option><option>Port</option></select></label>
        <label>Date text<input value={fieldDraft.dateText ?? ""} onChange={event => setFieldDraft(d => ({ ...d, dateText: event.target.value }))} /></label>
        <label>Date precision<select value={fieldDraft.datePrecision ?? "Exact"} onChange={event => setFieldDraft(d => ({ ...d, datePrecision: event.target.value }))}><option>Exact</option><option>Month</option><option>Window</option><option>Year</option><option>TBA</option></select></label>
        <label>Release date<input value={fieldDraft.releaseDate ?? ""} onChange={event => setFieldDraft(d => ({ ...d, releaseDate: event.target.value }))} placeholder="2027-02-20" /></label>
        <label>Release window<input value={fieldDraft.releaseWindow ?? ""} onChange={event => setFieldDraft(d => ({ ...d, releaseWindow: event.target.value }))} placeholder="Early 2027" /></label>
        <div className="settings-actions">
          <button type="button" className="action-sync" onClick={saveFieldEdit}>Save changes</button>
          <button type="button" className="secondary" onClick={cancelFieldEdit}>Cancel</button>
        </div>
      </div>
    );
  }

  return (
    <>
      <div className="ruled">
        <dl>
          <dt>Date</dt><dd>{detail.dateText} - {detail.datePrecision}</dd>
          <dt>Publisher</dt><dd>{detail.publishers.join(", ") || "-"}</dd>
          <dt>Developer</dt><dd>{detail.developers.join(", ") || "-"}</dd>
          <dt>Platforms</dt><dd>{detail.platforms.join(", ") || "-"}</dd>
          <dt>Category</dt><dd>{detail.category}</dd>
        </dl>
      </div>
      <div className="settings-actions" style={{ marginTop: "16px" }}>
        <button type="button" className="secondary" onClick={startFieldEdit}>Edit details</button>
      </div>
    </>
  );
}
