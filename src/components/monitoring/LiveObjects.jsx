import { objectLabel, formatDate } from "../../utils/formatters.js";

/**
 * LiveObjects – Real-time detection & change tracking against the saved room baseline.
 *
 * Props:
 *   isActive         boolean    – true when this tab is selected
 *   latest           object     – latest scan result { detections[], captured_at }
 *   baseline         object     – saved baseline layout { detections[], captured_at, room_name }
 *   liveComparison   object     – real-time comparison result { summary, missing[], new[], moved[], unchanged[] }
 *   knownObjectNames Set<string> – class names from the baseline (to flag new objects)
 *   cameraActive     boolean    – whether the camera is currently running
 *   monitoringState  string     – "active" | "moved" | "paused" | "idle"
 */
export default function LiveObjects({
  isActive,
  latest,
  baseline,
  liveComparison,
  knownObjectNames = new Set(),
  cameraActive,
  monitoringState = "active",
}) {
  const currentDetections = latest?.detections || [];
  const baselineDetections = baseline?.detections || [];

  // Extract change breakdown from liveComparison or fallback to baseline comparison
  const compDiff = liveComparison?.comparison || liveComparison;
  const missing = compDiff?.missing || compDiff?.not_currently_visible || [];
  const newObjects = compDiff?.new || compDiff?.newly_visible || [];
  const moved = compDiff?.moved || [];
  const unchanged = compDiff?.unchanged || [];

  const isCameraMoved = monitoringState === "moved";
  const isViewUnverified = monitoringState === "paused";
  const hasChanges = missing.length > 0 || newObjects.length > 0 || moved.length > 0;

  return (
    <div
      id="tab-panel-monitor"
      role="tabpanel"
      className={`tab-panel ${!isActive ? "tab-panel-hidden" : ""}`}
      aria-label="Live detected objects and room changes"
    >
      {/* ── 1. PROMINENT LIVE CHANGE TRACKING PANEL ── */}
      <div className="panel live-change-tracking-panel">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">ROOM CHANGE TRACKING</p>
            <h2>Live Status vs. Learned Baseline</h2>
          </div>
          {cameraActive && (
            <span className={`status-pill ${hasChanges ? "is-warning" : "is-live"}`}>
              {isCameraMoved
                ? "⚠️ Camera Moved"
                : isViewUnverified
                ? "⏸️ Unverified"
                : hasChanges
                ? "🚨 Changes Observed"
                : "🟢 Room Stable"}
            </span>
          )}
        </div>

        {/* Status Explanation Card */}
        {isCameraMoved ? (
          <div className="live-status-notice notice-warning" role="alert">
            <span className="notice-icon" aria-hidden="true">⚠️</span>
            <div>
              <strong>Camera Viewpoint Changed</strong>
              <p>The camera shifted from the learned room viewpoint. Live change tracking is paused to prevent false alerts. Align the camera with the original viewpoint or click &quot;Restore Camera View&quot;.</p>
            </div>
          </div>
        ) : isViewUnverified ? (
          <div className="live-status-notice notice-paused" role="status">
            <span className="notice-icon" aria-hidden="true">⏸️</span>
            <div>
              <strong>Camera View Unverified</strong>
              <p>Room lighting or viewpoint cannot be confirmed reliably. Alerts are paused until alignment stabilizes.</p>
            </div>
          </div>
        ) : !cameraActive ? (
          <p className="history-empty">
            Start the camera and monitoring to begin live change tracking against the saved baseline.
          </p>
        ) : (
          <div className="live-change-summary-grid">
            <div className={`summary-metric ${missing.length > 0 ? "metric-alert" : ""}`}>
              <span className="metric-number">{missing.length}</span>
              <span className="metric-label">Missing</span>
            </div>
            <div className={`summary-metric ${moved.length > 0 ? "metric-moved" : ""}`}>
              <span className="metric-number">{moved.length}</span>
              <span className="metric-label">Moved</span>
            </div>
            <div className={`summary-metric ${newObjects.length > 0 ? "metric-new" : ""}`}>
              <span className="metric-number">{newObjects.length}</span>
              <span className="metric-label">New Objects</span>
            </div>
            <div className="summary-metric metric-stable">
              <span className="metric-number">{unchanged.length}</span>
              <span className="metric-label">Unchanged</span>
            </div>
          </div>
        )}

        {/* Detailed Change Cards (Missing / Moved / New) */}
        {cameraActive && !isCameraMoved && (
          <div className="live-active-changes">
            {missing.length > 0 && (
              <div className="change-category category-missing" role="region" aria-label="Missing objects">
                <h3 className="category-title">
                  <span aria-hidden="true">🔴</span> Missing from Original Baseline ({missing.length})
                </h3>
                <ul className="live-card-list">
                  {missing.map((item, index) => (
                    <li key={`missing-${item.class_name}-${index}`} className="live-change-card card-missing">
                      <div className="live-card-badge-row">
                        <span className="live-badge badge-missing">MISSING</span>
                        <strong>{item.class_name}</strong>
                      </div>
                      <p className="live-card-meta">
                        Original Location: <strong>{item.zone || "Learned location"}</strong>
                      </p>
                      <p className="live-card-detail">
                        Present in baseline layout but not detected in current camera view.
                      </p>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {moved.length > 0 && (
              <div className="change-category category-moved" role="region" aria-label="Moved objects">
                <h3 className="category-title">
                  <span aria-hidden="true">🟡</span> Moved Objects ({moved.length})
                </h3>
                <ul className="live-card-list">
                  {moved.map((item, index) => (
                    <li key={`moved-${item.class_name}-${index}`} className="live-change-card card-moved">
                      <div className="live-card-badge-row">
                        <span className="live-badge badge-moved">MOVED</span>
                        <strong>{item.class_name}</strong>
                      </div>
                      <p className="live-card-meta">
                        Previous: <strong>{item.original_zone || item.previous_position?.zone || "Original zone"}</strong>
                        {" → "}
                        Current: <strong>{item.current_zone || item.current_position?.zone || "New zone"}</strong>
                      </p>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {newObjects.length > 0 && (
              <div className="change-category category-new" role="region" aria-label="New objects">
                <h3 className="category-title">
                  <span aria-hidden="true">🔵</span> Newly Appeared Objects ({newObjects.length})
                </h3>
                <ul className="live-card-list">
                  {newObjects.map((item, index) => (
                    <li key={`new-${item.class_name}-${index}`} className="live-change-card card-new">
                      <div className="live-card-badge-row">
                        <span className="live-badge badge-new">NEW OBJECT</span>
                        <strong>{item.class_name}</strong>
                      </div>
                      <p className="live-card-meta">
                        Detected in: <strong>{item.current_zone || item.zone || "Room"}</strong>
                      </p>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}
      </div>

      {/* ── 2. CURRENT DETECTED OBJECTS ── */}
      <div className="panel">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">CURRENT DETECTION</p>
            <h2>Objects in Camera View ({currentDetections.length})</h2>
          </div>
          {cameraActive && <span className="saved-badge">Live Feed</span>}
        </div>
        {currentDetections.length ? (
          <ul className="object-list latest-list" aria-label="Currently detected objects">
            {currentDetections.map((object, index) => {
              const isOutsideBaseline = !knownObjectNames.has(object.class_name) && cameraActive;
              return (
                <li
                  className={`object-card ${isOutsideBaseline ? "object-card-new" : ""}`}
                  key={`${object.class_name}-${object.instance_number ?? index}-${index}`}
                  aria-label={`${object.class_name}${isOutsideBaseline ? " — not in original layout" : ""}, zone: ${object.zone}`}
                >
                  <span className="object-symbol" aria-hidden="true">
                    {object.class_name.slice(0, 1).toUpperCase()}
                  </span>
                  <span className="object-description">
                    <strong>
                      {objectLabel(object)}
                      {isOutsideBaseline && <span className="pill-tag pill-tag-new">New</span>}
                    </strong>
                    <span>
                      {object.zone} | {Math.round(object.confidence * 100)}% confidence
                    </span>
                  </span>
                </li>
              );
            })}
          </ul>
        ) : (
          <p className="history-empty">
            {latest
              ? "No supported objects visible in the latest scan."
              : "Start monitoring to show the latest reliable camera observations."}
          </p>
        )}
        {latest?.captured_at && (
          <p className="saved-meta">Last scan: {formatDate(latest.captured_at)}</p>
        )}
      </div>

      {/* ── 3. ORIGINAL LEARNED BASELINE OBJECTS (REFERENCE) ── */}
      {baselineDetections.length > 0 && (
        <div className="panel baseline-reference-panel">
          <div className="panel-heading">
            <div>
              <p className="eyebrow">BASELINE REFERENCE</p>
              <h2>Learned Layout for {baseline.room_name} ({baselineDetections.length})</h2>
            </div>
            <span className="saved-badge">Baseline</span>
          </div>
          <ul className="object-list" aria-label="Baseline objects for comparison">
            {baselineDetections.map((object, index) => (
              <li
                className="object-card"
                key={`baseline-ref-${object.class_name}-${object.instance_number ?? index}-${index}`}
              >
                <span className="object-symbol" aria-hidden="true">
                  {object.class_name.slice(0, 1).toUpperCase()}
                </span>
                <span className="object-description">
                  <strong>{objectLabel(object)}</strong>
                  <span>{object.zone} | {Math.round(object.confidence * 100)}% confidence</span>
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
