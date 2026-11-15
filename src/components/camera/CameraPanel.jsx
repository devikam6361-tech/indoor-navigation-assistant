// CameraPanel — live webcam feed, start/stop controls, capture and re-capture buttons,
// and the comparison trigger button.
//
// Props:
//   effectiveRoomName      string   — displayed in the panel heading
//   cameraActive           bool     — whether the webcam is currently streaming
//   baselineDetectionCount number   — detection count from saved baseline (0 = no baseline)
//   baselineLoading        bool     — true while the baseline is being fetched
//   busy                   bool     — true while a capture request is in-flight
//   hasCurrentRoomBaseline bool     — baseline exists for the currently selected room
//   hasLatest              bool     — a latest observation exists (enables comparison button)
//   videoRef               ref      — attached to the <video> element
//   canvasRef              ref      — attached to the hidden capture <canvas>
//   onStart                fn()     — start camera
//   onStop                 fn()     — stop camera
//   onCapture              fn(bool) — capture layout; true = replace existing
//   onShowComparison       fn()     — open the before/after comparison modal
export default function CameraPanel({
  effectiveRoomName,
  cameraActive,
  baselineDetectionCount,
  baselineLoading,
  busy,
  hasCurrentRoomBaseline,
  hasLatest,
  videoRef,
  canvasRef,
  onStart,
  onStop,
  onCapture,
  onShowComparison,
}) {
  return (
    <div className="panel camera-panel">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">LIVE CAMERA</p>
          <h2 id="camera-heading">
            {effectiveRoomName || "Select a room"} — Camera
          </h2>
        </div>
        <span
          className={`status-pill ${cameraActive ? "is-live" : ""}`}
          aria-live="polite"
        >
          <span aria-hidden="true" className="status-dot" />
          {cameraActive
            ? (baselineDetectionCount ? "Monitoring" : "Camera on")
            : "Camera off"}
        </span>
      </div>

      <div className="camera-frame" aria-label="Camera preview">
        <video ref={videoRef} autoPlay muted playsInline aria-label="Live webcam feed" />
        {!cameraActive && (
          <div className="camera-placeholder" role="img" aria-label="Camera is off">
            <span className="camera-icon" aria-hidden="true">
              <svg viewBox="0 0 24 24" aria-hidden="true">
                <path d="M4 7h3l1.5-2h7L17 7h3v12H4z" />
                <circle cx="12" cy="13" r="4" />
              </svg>
            </span>
            <p>Start the webcam to preview and monitor this room</p>
            <p className="camera-hint">Keep the camera fixed in its learned position.</p>
          </div>
        )}
      </div>

      <div className="camera-controls" aria-label="Camera and layout controls">
        <div className="button-row">
          {!cameraActive ? (
            <button
              className="button button-secondary"
              disabled={baselineLoading}
              onClick={onStart}
              aria-label="Start monitoring camera"
            >
              {baselineDetectionCount ? "▶ Start Monitoring" : "▶ Start Webcam"}
            </button>
          ) : (
            <button
              className="button button-secondary"
              onClick={onStop}
              aria-label="Stop monitoring camera"
            >
              ⏹ Stop {baselineDetectionCount ? "Monitoring" : "Camera"}
            </button>
          )}

          <button
            className="button button-primary"
            disabled={!cameraActive || busy || !effectiveRoomName || hasCurrentRoomBaseline}
            onClick={() => onCapture(false)}
            aria-label="Capture original room layout"
          >
            {busy
              ? "Saving layout..."
              : hasCurrentRoomBaseline
              ? "✓ Layout Saved"
              : "📷 Capture Original Layout"}
          </button>
        </div>

        {cameraActive && hasCurrentRoomBaseline && (
          <button
            className="relearn-button"
            disabled={busy}
            onClick={() => onCapture(true)}
            aria-label="Replace saved layout with current view"
          >
            🔄 Re-capture layout (replaces saved baseline)
          </button>
        )}

        {hasCurrentRoomBaseline && hasLatest && (
          <button
            className="compare-button"
            onClick={onShowComparison}
            aria-label="View before and after comparison"
          >
            🔍 View Before &amp; After Comparison
          </button>
        )}
      </div>

      <canvas className="capture-canvas" ref={canvasRef} aria-hidden="true" />
    </div>
  );
}
