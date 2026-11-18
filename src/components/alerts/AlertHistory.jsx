import { formatDate } from "../../utils/formatters.js";

/**
 * AlertHistory – "Alert History" monitoring tab panel.
 *
 * Props:
 *   isActive   boolean  – true when this tab is selected (controls visibility class)
 *   history    array    – alert event objects from App state
 *   onRepeat   () => void – calls repeatAlertReport in App to replay voice alerts
 */
export default function AlertHistory({ isActive, history, onRepeat }) {
  return (
    <div
      id="tab-panel-history"
      role="tabpanel"
      className={`tab-panel ${!isActive ? "tab-panel-hidden" : ""}`}
      aria-label="Change alert history"
    >
      <div className="panel">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">CONFIRMED CHANGES</p>
            <h2>Alert history</h2>
          </div>
          <button
            className="repeat-button"
            disabled={!history.length}
            onClick={onRepeat}
            aria-label="Repeat recent alerts by voice"
          >
            🔊 Repeat report
          </button>
        </div>
        {history.length ? (
          <ol className="history-list" aria-label="Change alert history list">
            {history.map((event) => (
              <li className="history-item" key={event.id}>
                <span
                  className={`change-badge change-${event.change_type}`}
                  aria-label={`Change type: ${event.change_type}`}
                >
                  {event.change_type.startsWith("camera_view_")
                    ? "Camera status"
                    : event.change_type === "moved"
                    ? "Moved"
                    : event.change_type === "newly_observed"
                    ? "New object"
                    : "Not visible"}
                </span>
                <p className="history-message">{event.message}</p>
                <p className="history-meta">
                  {event.object_name} | {formatDate(event.created_at)}
                  {event.confidence !== null && ` | ${Math.round(event.confidence * 100)}% confidence`}
                </p>
                <p className="history-meta">
                  Voice:{" "}
                  {event.speech_status === "spoken"
                    ? "✓ played"
                    : event.speech_status === "failed"
                    ? `✗ failed${event.speech_error ? ` — ${event.speech_error}` : ""}`
                    : event.speech_status === "unavailable"
                    ? "unavailable"
                    : "pending"}
                </p>
              </li>
            ))}
          </ol>
        ) : (
          <p className="history-empty">
            No confirmed changes yet. Alerts are created only after a change appears in 3 consecutive reliable scans.
          </p>
        )}
      </div>
    </div>
  );
}
