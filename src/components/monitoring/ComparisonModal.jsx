import DetectionOverlay from "../camera/DetectionOverlay.jsx";
import { formatDate } from "../../utils/formatters.js";

/**
 * ComparisonModal – Before/After room comparison dialog.
 *
 * Props:
 *   comparison       {baseline, latest, comparison} – comparison data from App state
 *   effectiveRoomName string                        – display name of the current room
 *   onClose          () => void                     – called when the user closes the modal
 */
export default function ComparisonModal({ comparison, effectiveRoomName, onClose }) {
  const diff = comparison?.comparison;
  const summary = diff?.summary;
  const moved = diff?.moved ?? [];
  const newItems = diff?.new ?? [];
  const missing = diff?.missing ?? [];
  const unchanged = diff?.unchanged ?? [];

  return (
    <div
      className="comparison-backdrop"
      role="dialog"
      aria-modal="true"
      aria-label="Before and after room comparison"
      onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
    >
      <div className="comparison-modal">
        <div className="comparison-header">
          <h2>Before &amp; After Comparison — {effectiveRoomName}</h2>
          <button
            className="close-button"
            onClick={onClose}
            aria-label="Close comparison"
          >
            ✕
          </button>
        </div>

        <div className="comparison-grid">
          <DetectionOverlay
            imageUrl={comparison?.baseline?.image_data_url}
            detections={comparison?.baseline?.detections}
            label={`Original layout — ${formatDate(comparison?.baseline?.captured_at)}`}
          />
          <DetectionOverlay
            imageUrl={comparison?.latest?.image_data_url}
            detections={comparison?.latest?.detections}
            label={`Latest scan — ${comparison?.latest ? formatDate(comparison.latest.captured_at) : "Not yet scanned"}`}
          />
        </div>

        {summary && (
          <div className="comparison-metrics" aria-label="Comparison summary statistics">
            <div className="metric-pill metric-unchanged">
              <span className="metric-icon">🟢</span>
              <span className="metric-label">Unchanged:</span>
              <span className="metric-count">{summary.unchanged}</span>
            </div>
            <div className="metric-pill metric-moved">
              <span className="metric-icon">🟡</span>
              <span className="metric-label">Moved:</span>
              <span className="metric-count">{summary.moved}</span>
            </div>
            <div className="metric-pill metric-new">
              <span className="metric-icon">🔵</span>
              <span className="metric-label">New:</span>
              <span className="metric-count">{summary.new}</span>
            </div>
            <div className="metric-pill metric-missing">
              <span className="metric-icon">🔴</span>
              <span className="metric-label">Missing:</span>
              <span className="metric-count">{summary.missing}</span>
            </div>
          </div>
        )}

        <div className="comparison-categories-grid">
          {/* MOVED OBJECTS */}
          <section className="category-section category-moved" aria-labelledby="heading-moved">
            <h3 id="heading-moved" className="category-heading">
              <span className="category-tag tag-moved">Moved ({moved.length})</span>
            </h3>
            {moved.length === 0 ? (
              <p className="category-empty">No moved objects detected.</p>
            ) : (
              <ul className="category-list">
                {moved.map((item, idx) => (
                  <li key={`moved-${item.instance_label || item.label}-${idx}`} className="category-card card-moved">
                    <div className="card-header">
                      <strong>{item.instance_label || item.label}</strong>
                      {item.confidence != null && (
                        <span className="confidence-badge">{Math.round(item.confidence * 100)}%</span>
                      )}
                    </div>
                    <div className="card-details">
                      <div className="zone-transition">
                        <span className="zone-tag zone-prev">{item.previous_zone || "unknown"}</span>
                        <span className="zone-arrow" aria-hidden="true">→</span>
                        <span className="zone-tag zone-curr">{item.current_zone || "unknown"}</span>
                      </div>
                      {item.distance != null && (
                        <span className="distance-info">
                          Shift: ~{Math.round(item.distance * 100)}% of view
                        </span>
                      )}
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </section>

          {/* NEW OBJECTS */}
          <section className="category-section category-new" aria-labelledby="heading-new">
            <h3 id="heading-new" className="category-heading">
              <span className="category-tag tag-new">New ({newItems.length})</span>
            </h3>
            {newItems.length === 0 ? (
              <p className="category-empty">No new objects detected.</p>
            ) : (
              <ul className="category-list">
                {newItems.map((item, idx) => (
                  <li key={`new-${item.instance_label || item.label}-${idx}`} className="category-card card-new">
                    <div className="card-header">
                      <strong>{item.instance_label || item.label}</strong>
                      {item.confidence != null && (
                        <span className="confidence-badge">{Math.round(item.confidence * 100)}%</span>
                      )}
                    </div>
                    <div className="card-details">
                      <span>Detected in: <strong className="zone-highlight">{item.zone || "unknown"}</strong></span>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </section>

          {/* MISSING OBJECTS */}
          <section className="category-section category-missing" aria-labelledby="heading-missing">
            <h3 id="heading-missing" className="category-heading">
              <span className="category-tag tag-missing">Missing ({missing.length})</span>
            </h3>
            {missing.length === 0 ? (
              <p className="category-empty">No missing objects.</p>
            ) : (
              <ul className="category-list">
                {missing.map((item, idx) => (
                  <li key={`missing-${item.instance_label || item.label}-${idx}`} className="category-card card-missing">
                    <div className="card-header">
                      <strong>{item.instance_label || item.label}</strong>
                      {item.confidence != null && (
                        <span className="confidence-badge">{Math.round(item.confidence * 100)}%</span>
                      )}
                    </div>
                    <div className="card-details">
                      <span>Original position: <strong className="zone-highlight">{item.last_zone || "unknown"}</strong></span>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </section>

          {/* UNCHANGED OBJECTS */}
          <section className="category-section category-unchanged" aria-labelledby="heading-unchanged">
            <h3 id="heading-unchanged" className="category-heading">
              <span className="category-tag tag-unchanged">Unchanged ({unchanged.length})</span>
            </h3>
            {unchanged.length === 0 ? (
              <p className="category-empty">No unchanged objects.</p>
            ) : (
              <ul className="category-list">
                {unchanged.map((item, idx) => (
                  <li key={`unchanged-${item.instance_label || item.label}-${idx}`} className="category-card card-unchanged">
                    <div className="card-header">
                      <strong>{item.instance_label || item.label}</strong>
                      {item.confidence != null && (
                        <span className="confidence-badge">{Math.round(item.confidence * 100)}%</span>
                      )}
                    </div>
                    <div className="card-details">
                      <span>Position: <strong className="zone-highlight">{item.zone || "unknown"}</strong></span>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </div>

        {comparison?.baseline && comparison?.latest && (
          <div className="comparison-summary">
            <p>
              <strong>Original Baseline:</strong> {comparison.baseline.detections?.length || 0} object{(comparison.baseline.detections?.length || 0) !== 1 ? "s" : ""}
              &nbsp;|&nbsp;
              <strong>Latest Scan:</strong> {comparison.latest.detections?.length || 0} object{(comparison.latest.detections?.length || 0) !== 1 ? "s" : ""}
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
