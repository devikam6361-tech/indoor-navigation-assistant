import { useEffect } from "react";
import { formatDate } from "../../utils/formatters.js";
import DetectionOverlay from "../camera/DetectionOverlay.jsx";
import {
  formatComparisonAnnouncement,
  isSpeechSynthesisSupported,
} from "../../voice/voiceSynthesis.js";

function layoutLabel(label, layout) {
  if (!layout) return label;
  const capturedAt = layout.captured_at
    ? ` — ${formatDate(layout.captured_at)}`
    : "";
  return `${label}${capturedAt}`;
}

function getDetectionResults(layout) {
  if (!Array.isArray(layout?.detections)) {
    return { status: "unavailable", detections: [] };
  }
  if (layout.detections.length === 0) {
    return { status: "empty", detections: [] };
  }

  const detections = layout.detections.filter((detection) => {
    if (
      !detection
      || typeof detection.class_name !== "string"
      || !detection.class_name.trim()
      || !Number.isFinite(detection.confidence)
      || detection.confidence < 0
      || detection.confidence > 1
    ) {
      return false;
    }

    const coordinates = [detection.x1, detection.y1, detection.x2, detection.y2];
    return (
      coordinates.every((coordinate) =>
        Number.isFinite(coordinate) && coordinate >= 0 && coordinate <= 1,
      )
      && detection.x1 < detection.x2
      && detection.y1 < detection.y2
    );
  });

  if (detections.length === 0) {
    return { status: "invalid", detections: [] };
  }
  return {
    status: detections.length === layout.detections.length ? "available" : "partial",
    detections,
  };
}

function DetectionResults({ result, label }) {
  const countUnavailable = result.status === "unavailable" || result.status === "invalid";

  return (
    <div className="detection-results comparison-detection-results" aria-label={`${label} detection results`}>
      <p className="detection-count">
        {countUnavailable
          ? "Detection count unavailable."
          : `${result.detections.length} detected object${result.detections.length === 1 ? "" : "s"}.`}
      </p>
      {result.status === "empty" && (
        <p className="detection-results-message">
          No supported objects detected in this image.
        </p>
      )}
      {result.status === "unavailable" && (
        <p className="detection-results-message">
          Detection results are unavailable for this image.
        </p>
      )}
      {result.status === "invalid" && (
        <p className="detection-results-message" role="status">
          Detection results could not be displayed because the response was invalid.
        </p>
      )}
      {result.status === "partial" && (
        <p className="detection-results-message" role="status">
          Some invalid detection results were omitted.
        </p>
      )}
      {result.detections.length > 0 && (
        <ul className="object-list detection-object-list" aria-label={`${label} detected objects`}>
          {result.detections.map((detection, index) => (
            <li
              className="object-card"
              key={`${detection.class_name}-${detection.instance_number ?? index}-${index}`}
            >
              <span className="object-symbol" aria-hidden="true">
                {detection.class_name.trim().slice(0, 1).toUpperCase()}
              </span>
              <span className="object-description">
                <strong>{detection.class_name.trim()}</strong>
                <span>{Math.round(detection.confidence * 100)}% confidence</span>
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function ComparisonLayout({ layout, label, effectiveRoomName }) {
  const displayLabel = layoutLabel(label, layout);
  const detections = getDetectionResults(layout);
  const imageUrl = typeof layout?.image_data_url === "string"
    && layout.image_data_url.startsWith("data:image/")
    ? layout.image_data_url
    : "";

  return (
    <section className="comparison-layout-column">
      {imageUrl ? (
        <DetectionOverlay
          imageUrl={imageUrl}
          detections={detections.detections}
          label={displayLabel}
        />
      ) : (
        <div className="overlay-wrapper">
          <p className="overlay-label">{displayLabel}</p>
          <p className="empty-state">
            The saved {label.startsWith("BEFORE") ? "BEFORE" : "AFTER"} image for {effectiveRoomName} is unavailable.
          </p>
        </div>
      )}
      <DetectionResults result={detections} label={label} />
    </section>
  );
}

export default function ComparisonModal({
  comparison,
  effectiveRoomName,
  voiceEnabled = true,
  onReplayVoice,
  onTestVoice,
  onToggleVoice,
  onClose,
}) {
  const status = comparison?.status || "error";
  const diff = comparison?.comparison;
  const moved = diff?.moved || [];
  const missing = diff?.missing || diff?.not_currently_visible || [];
  const newlyVisible = diff?.new || diff?.newly_visible || [];
  const unchanged = diff?.unchanged || [];

  const announcement = formatComparisonAnnouncement(comparison, effectiveRoomName);

  // Keyboard escape handler for accessibility
  useEffect(() => {
    function handleKeyDown(event) {
      if (event.key === "Escape") {
        onClose();
      }
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [onClose]);

  return (
    <div
      className="comparison-backdrop"
      role="dialog"
      aria-modal="true"
      aria-label="Saved BEFORE and AFTER room comparison"
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div className="comparison-modal">
        {/* Header with Title and Voice Controls */}
        <div className="comparison-header">
          <div>
            <h2>Before &amp; After Comparison — {effectiveRoomName}</h2>
            <p className="comparison-room-meta">
              Comparing room arrangement between saved snapshots
            </p>
          </div>
          <div className="comparison-header-actions">
            {isSpeechSynthesisSupported() && (
              <div className="modal-voice-controls">
                <button
                  type="button"
                  className="voice-btn voice-test-btn"
                  onClick={() => onTestVoice?.()}
                  title="Test browser speech audio playback"
                  aria-label="Test voice announcement"
                >
                  🧪 Test Voice
                </button>
                <button
                  type="button"
                  className="voice-btn voice-replay-btn"
                  onClick={() => onReplayVoice?.(announcement)}
                  title="Replay spoken change alert"
                  aria-label="Replay voice announcement"
                >
                  🔊 Replay Voice
                </button>
                {onToggleVoice && (
                  <button
                    type="button"
                    className={`voice-btn voice-toggle-btn ${voiceEnabled ? "voice-on" : "voice-muted"}`}
                    onClick={onToggleVoice}
                    aria-label={voiceEnabled ? "Mute voice alerts" : "Unmute voice alerts"}
                  >
                    {voiceEnabled ? "Voice: ON" : "Voice: MUTED"}
                  </button>
                )}
              </div>
            )}
            <button
              className="close-button"
              onClick={onClose}
              aria-label="Close comparison"
              type="button"
            >
              ✕
            </button>
          </div>
        </div>

        {/* ── PROMINENT CHANGE ALERT SECTION ── */}
        <section
          className={`change-alert-section change-alert-${status}`}
          role="region"
          aria-label="Change alerts between BEFORE and AFTER"
        >
          {status === "changed" && (
            <div className="change-alert-box change-alert-box-changed">
              <div className="change-alert-banner">
                <span className="change-alert-icon" aria-hidden="true">🚨</span>
                <div className="change-alert-banner-text">
                  <h3 className="change-alert-heading">
                    CHANGE DETECTED: Room Arrangement Modified
                  </h3>
                  <p className="change-alert-subtext">
                    {missing.length > 0 && `${missing.length} missing • `}
                    {moved.length > 0 && `${moved.length} moved • `}
                    {newlyVisible.length > 0 && `${newlyVisible.length} new • `}
                    {unchanged.length} unchanged
                  </p>
                </div>
              </div>

              <div className="change-cards-container">
                {/* Missing Objects */}
                {missing.map((item, index) => (
                  <div
                    key={`missing-${item.class_name}-${item.instance_number ?? index}-${index}`}
                    className="change-card card-missing"
                  >
                    <div className="change-card-badge-row">
                      <span className="change-tag tag-missing">MISSING</span>
                      <strong className="change-card-title">{item.class_name}</strong>
                    </div>
                    <p className="change-card-position">
                      Previous Position: <strong>{item.zone || "Learned location"}</strong>
                    </p>
                    <p className="change-card-message">
                      CHANGE DETECTED: The {item.class_name} was present in the BEFORE image but is missing in the AFTER image.
                    </p>
                  </div>
                ))}

                {/* Moved Objects */}
                {moved.map((item, index) => (
                  <div
                    key={`moved-${item.class_name}-${item.instance_number ?? index}-${index}`}
                    className="change-card card-moved"
                  >
                    <div className="change-card-badge-row">
                      <span className="change-tag tag-moved">MOVED</span>
                      <strong className="change-card-title">{item.class_name}</strong>
                    </div>
                    <p className="change-card-position">
                      Previous: <strong>{item.original_zone || item.previous_position?.zone || "Original position"}</strong>
                      {" → "}
                      Current: <strong>{item.current_zone || item.current_position?.zone || "New position"}</strong>
                    </p>
                    <p className="change-card-message">
                      CHANGE DETECTED: The {item.class_name} has moved from its previous position.
                    </p>
                  </div>
                ))}

                {/* New Objects */}
                {newlyVisible.map((item, index) => (
                  <div
                    key={`new-${item.class_name}-${item.instance_number ?? index}-${index}`}
                    className="change-card card-new"
                  >
                    <div className="change-card-badge-row">
                      <span className="change-tag tag-new">NEW OBJECT</span>
                      <strong className="change-card-title">{item.class_name}</strong>
                    </div>
                    <p className="change-card-position">
                      Current Position: <strong>{item.current_zone || item.zone || "New location"}</strong>
                    </p>
                    <p className="change-card-message">
                      CHANGE DETECTED: A new object ({item.class_name}) has appeared in the room.
                    </p>
                  </div>
                ))}
              </div>
            </div>
          )}

          {status === "unchanged" && (
            <div className="change-alert-box change-alert-box-unchanged" role="status">
              <span className="no-change-icon" aria-hidden="true">✅</span>
              <div>
                <h3 className="no-change-heading">No Significant Changes Detected</h3>
                <p className="no-change-message">
                  No significant changes detected between BEFORE and AFTER.
                </p>
              </div>
            </div>
          )}

          {status === "uncertain" && (
            <div className="change-alert-box change-alert-box-uncertain" role="alert">
              <span className="uncertain-icon" aria-hidden="true">⚠️</span>
              <div>
                <h3 className="uncertain-heading">Unable to Confirm Room Arrangement</h3>
                <p className="uncertain-message">
                  The camera viewpoint or room lighting changed significantly between BEFORE and AFTER.
                  Please align the camera or recapture to confirm changes safely.
                </p>
              </div>
            </div>
          )}

          {status === "error" && (
            <div className="change-alert-box change-alert-box-error" role="alert">
              <span className="error-icon" aria-hidden="true">❌</span>
              <div>
                <h3 className="error-heading">Comparison Failed</h3>
                <p className="error-message">
                  {comparison?.error || "An error occurred while comparing BEFORE and AFTER layouts."}
                </p>
              </div>
            </div>
          )}
        </section>

        {/* ── BEFORE & AFTER SIDE-BY-SIDE IMAGES ── */}
        <div className="comparison-grid">
          <ComparisonLayout
            layout={comparison?.before}
            label="BEFORE — Original arrangement"
            effectiveRoomName={effectiveRoomName}
          />
          <ComparisonLayout
            layout={comparison?.after}
            label="AFTER — Updated arrangement"
            effectiveRoomName={effectiveRoomName}
          />
        </div>

        {/* Unchanged Objects (if any) */}
        {unchanged.length > 0 && status === "changed" && (
          <div className="unchanged-objects-summary">
            <h4>Unchanged Objects ({unchanged.length})</h4>
            <div className="unchanged-badges-list">
              {unchanged.map((item, index) => (
                <span
                  key={`unchanged-${item.class_name}-${index}`}
                  className="unchanged-pill"
                >
                  ✓ {item.class_name} ({item.zone || "in place"})
                </span>
              ))}
            </div>
          </div>
        )}

        {comparison?.speechWarning && (
          <p className="layout-message layout-error" role="status">
            {comparison.speechWarning}
          </p>
        )}
      </div>
    </div>
  );
}
