import { formatDate, objectLabel } from "../../utils/formatters.js";

// BaselinePanel — shows the saved original room layout: the snapshot image,
// the list of detected objects with zones and confidence scores, and
// an empty-state prompt when no baseline exists yet.
//
// Props:
//   baseline               object|null  — baseline response from Flask API (or null)
//   baselineLoading        bool         — true while fetching the baseline
//   hasCurrentRoomBaseline bool         — baseline exists for the selected room
//   effectiveRoomName      string       — displayed in the empty-state message
export default function BaselinePanel({
  baseline,
  baselineLoading,
  hasCurrentRoomBaseline,
  effectiveRoomName,
}) {
  return (
    <section
      className="panel memory-panel"
      aria-live="polite"
      aria-label="Saved original layout"
    >
      <div className="panel-heading">
        <div>
          <p className="eyebrow">ORIGINAL LAYOUT</p>
          <h2>Saved arrangement</h2>
        </div>
        {hasCurrentRoomBaseline && (
          <span className="saved-badge" aria-label="Layout saved">✓ Saved</span>
        )}
      </div>

      {baselineLoading ? (
        <p className="empty-state" aria-live="polite">Loading saved room memory...</p>
      ) : hasCurrentRoomBaseline ? (
        <>
          <img
            alt={`Saved camera view of ${baseline.room_name}`}
            className="baseline-image"
            src={baseline.image_data_url}
          />
          <p className="saved-meta">
            {baseline.room_name} | Captured {formatDate(baseline.captured_at)}
          </p>
          <p className="detection-count">
            {baseline.detections.length} object{baseline.detections.length === 1 ? "" : "s"} recorded
          </p>
          {baseline.detections.length ? (
            <ul className="object-list" aria-label="Detected objects in baseline">
              {baseline.detections.map((object) => (
                <li
                  className="object-card"
                  key={`${object.class_name}-${object.instance_number}`}
                  aria-label={`${object.class_name}, zone: ${object.zone}, confidence ${Math.round(object.confidence * 100)}%`}
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
          ) : (
            <p className="empty-state">
              No supported objects detected. Reframe camera and re-capture layout.
            </p>
          )}
          <p className="identity-note">
            Zones are approximate image regions. Object numbers are per-scan, not persistent identities.
          </p>
        </>
      ) : (
        <div className="empty-state">
          <span className="empty-icon" aria-hidden="true">
            <svg viewBox="0 0 24 24">
              <path d="m3 10 9-7 9 7v11h-7v-7h-4v7H3z" />
            </svg>
          </span>
          <p>No saved layout for <strong>{effectiveRoomName || "this room"}</strong>.</p>
          <p>Start the webcam, point it at the room, and click <strong>Capture Original Layout</strong>.</p>
        </div>
      )}
    </section>
  );
}
