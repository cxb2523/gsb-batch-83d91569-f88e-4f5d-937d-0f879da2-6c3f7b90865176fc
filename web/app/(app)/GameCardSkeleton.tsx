export default function GameCardSkeleton() {
  return (
    <div className="gcard" aria-hidden="true">
      <div className="gcard-cover skeleton" />
      <div className="gcard-body">
        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          <div className="skeleton skel-line" style={{ width: "90%" }} />
          <div className="skeleton skel-line" style={{ width: "60%" }} />
        </div>

        <div className="gcard-field">
          <div className="skeleton skel-line" style={{ width: "40%", height: 8, marginBottom: 4 }} />
          <div className="skeleton gcard-select" style={{ height: 30 }} />
        </div>

        <div className="gcard-actions">
          <div className="skeleton btn-ghost" />
          <div className="skeleton icon-btn" />
          <div className="skeleton icon-btn" />
        </div>
      </div>
    </div>
  );
}
