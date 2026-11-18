// CameraPanel — live webcam feed, start/stop controls, capture and re-capture buttons,
// live bounding box detection overlay on video, HUD status, and voice controls.
//
// Props:
//   effectiveRoomName      string   — displayed in the panel heading
//   cameraActive           bool     — whether the webcam is currently streaming
//   cameraStarting         bool     — whether camera startup is still pending
//   cameraStartCanceled    bool     — whether the pending startup was canceled
//   baselineDetectionCount number   — detection count from saved baseline (0 = no baseline)
//   baselineLoading        bool     — true while the baseline is being fetched
//   busy                   bool     — true while a capture request is in-flight
//   hasCurrentRoomBaseline bool     — baseline exists for the currently selected room
//   canCompareSavedLayouts bool     — both BEFORE and AFTER layouts have been saved
//   monitoringState        string   — "active" | "moved" | "paused" | "idle"
//   monitorMessage         string   — message explaining current status or pause reason
//   voiceEnabled           bool     — whether voice alerts are unmuted
//   voiceUnlocked          bool     — whether Web Speech API has been unlocked by user gesture
//   liveDetections         array    — latest detected objects { class_name, confidence, x1, y1, x2, y2, zone }
//   knownObjectNames       Set      — class names from the baseline (for tagging new objects)
//   lastScanTime           string   — formatted time of the last scan
//   videoRef               ref      — attached to the <video> element
//   canvasRef              ref      — attached to the hidden capture <canvas>
//   onStart                fn()     — start camera
//   onStop                 fn()     — stop camera
//   onCapture              fn(bool) — capture layout; true = replace existing
//   onShowComparison       fn()     — compare the selected saved BEFORE/AFTER layouts
//   onRestoreView          fn()     — restore camera viewpoint or re-check stability
//   onInitializeVoice      fn()     — direct user gesture to unlock Web Speech API in Chrome
//   onReplayVoice          fn()     — replay latest spoken alert
//   onTestVoice            fn()     — test speech synthesis playback
//   onToggleVoice          fn()     — toggle mute/unmute
import { useEffect, useRef } from "react";

function LiveDetectionOverlay({ videoRef, detections = [], knownObjectNames = new Set(), cameraActive }) {
  const canvasRef = useRef(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    const video = videoRef.current;
    if (!canvas || !video) return;

    function renderBoxes() {
      if (typeof canvas.getContext !== "function") return;
      let ctx;
      try {
        ctx = canvas.getContext("2d");
      } catch {
        return;
      }
      if (!ctx) return;

      if (!cameraActive || video.readyState < HTMLMediaElement.HAVE_CURRENT_DATA) {
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        return;
      }

      const clientW = video.clientWidth;
      const clientH = video.clientHeight;
      if (clientW === 0 || clientH === 0) return;

      canvas.width = clientW;
      canvas.height = clientH;
      ctx.clearRect(0, 0, clientW, clientH);

      const videoW = video.videoWidth || 640;
      const videoH = video.videoHeight || 480;

      // Calculate exact rendered video box inside letterbox/pillarbox container
      const clientRatio = clientW / clientH;
      const videoRatio = videoW / videoH;
      let renderW = clientW;
      let renderH = clientH;
      let renderX = 0;
      let renderY = 0;

      if (clientRatio > videoRatio) {
        // Pillarboxed (bars on left/right)
        renderH = clientH;
        renderW = renderH * videoRatio;
        renderX = (clientW - renderW) / 2;
      } else {
        // Letterboxed (bars on top/bottom)
        renderW = clientW;
        renderH = renderW / videoRatio;
        renderY = (clientH - renderH) / 2;
      }

      if (!detections || !detections.length) return;

      detections.forEach((det) => {
        if (!det || typeof det.x1 !== "number") return;
        const x = renderX + Math.max(0, Math.min(1, det.x1)) * renderW;
        const y = renderY + Math.max(0, Math.min(1, det.y1)) * renderH;
        const w = Math.max(8, (Math.min(1, det.x2) - Math.max(0, det.x1)) * renderW);
        const h = Math.max(8, (Math.min(1, det.y2) - Math.max(0, det.y1)) * renderH);

        const isNew = det.is_new || (knownObjectNames && !knownObjectNames.has(det.class_name));
        const isMoved = det.is_moved;

        // Visual distinction: Green for normal, Blue for new object, Amber for moved
        const color = isNew ? "#3b82f6" : isMoved ? "#f59e0b" : "#10b981";

        // Bounding box rectangle
        ctx.strokeStyle = color;
        ctx.lineWidth = 3;
        ctx.strokeRect(x, y, w, h);

        // Label banner
        const confPercent = Number.isFinite(det.confidence) ? `${Math.round(det.confidence * 100)}%` : "";
        const zoneText = det.zone ? ` • ${det.zone}` : "";
        const label = `${det.class_name} ${confPercent}${zoneText}`;

        ctx.font = "bold 12px system-ui, -apple-system, sans-serif";
        const textWidth = ctx.measureText(label).width + 8;
        const textHeight = 18;

        ctx.fillStyle = color;
        const tagY = Math.max(0, y - textHeight);
        ctx.fillRect(x, tagY, textWidth, textHeight);

        ctx.fillStyle = "#ffffff";
        ctx.fillText(label, x + 4, tagY + 13);
      });
    }

    renderBoxes();
    const handleResize = () => renderBoxes();
    window.addEventListener("resize", handleResize);
    return () => window.removeEventListener("resize", handleResize);
  }, [videoRef, detections, knownObjectNames, cameraActive]);

  return (
    <canvas
      ref={canvasRef}
      className="live-detection-overlay"
      aria-label="Live detection bounding boxes overlay"
      aria-hidden="true"
    />
  );
}

export default function CameraPanel({
  effectiveRoomName,
  cameraActive,
  cameraStarting,
  cameraStartCanceled,
  baselineDetectionCount,
  baselineLoading,
  busy,
  hasCurrentRoomBaseline,
  canCompareSavedLayouts,
  monitoringState = "idle",
  monitorMessage = "",
  voiceEnabled = true,
  voiceUnlocked = false,
  liveDetections = [],
  knownObjectNames = new Set(),
  lastScanTime = "",
  videoRef,
  canvasRef,
  onStart,
  onStop,
  onCapture,
  onShowComparison,
  onRestoreView,
  onInitializeVoice,
  onReplayVoice,
  onTestVoice,
  onToggleVoice,
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
            : cameraStartCanceled
            ? "Canceling startup"
            : cameraStarting
            ? "Starting camera"
            : "Camera off"}
        </span>
      </div>

      {/* ── PROMINENT MONITORING STATUS BANNER ── */}
      {cameraActive && (
        <div
          className={`monitoring-status-banner status-banner-${monitoringState}`}
          role="status"
          aria-live="polite"
        >
          <div className="status-banner-main">
            <span className="status-banner-badge">
              {monitoringState === "active" && "🟢 Monitoring Active"}
              {monitoringState === "moved" && "⚠️ Camera Moved — Monitoring Paused"}
              {monitoringState === "paused" && "⏸️ Monitoring Paused"}
              {monitoringState === "idle" && "⚪ Camera Standby"}
            </span>
            <p className="status-banner-text">
              {monitoringState === "moved"
                ? "The camera viewpoint shifted from the learned room baseline. Change alerts are paused to prevent false warnings."
                : monitoringState === "paused"
                ? (monitorMessage || "Camera view cannot be verified. Monitoring is paused.")
                : "Monitoring this camera view for confirmed changes. Room is stable."}
            </p>
          </div>
          {monitoringState === "moved" && (
            <div className="status-banner-actions">
              <button
                type="button"
                className="banner-action-btn btn-restore"
                onClick={onRestoreView}
                aria-label="Restore camera alignment"
              >
                🔄 Restore Camera View
              </button>
              <button
                type="button"
                className="banner-action-btn btn-recapture"
                disabled={busy}
                onClick={() => onCapture(true)}
                aria-label="Recapture room baseline with current camera viewpoint"
              >
                📷 Recapture Baseline
              </button>
            </div>
          )}
        </div>
      )}

      {/* ── VOICE ALERTS TOOLBAR ── */}
      <div className="voice-toolbar" role="toolbar" aria-label="Voice alert controls">
        <button
          type="button"
          className={`voice-action-btn ${voiceUnlocked ? "voice-btn-active" : "voice-btn-init"}`}
          onClick={onInitializeVoice}
          title="Direct user interaction to permit Chrome speech playback"
          aria-label={voiceUnlocked ? "Voice alerts active" : "Initialize voice alerts"}
        >
          {voiceUnlocked ? "🎙️ Voice Initialized" : "🎙️ Enable / Initialize Voice"}
        </button>
        <button
          type="button"
          className={`voice-action-btn ${voiceEnabled ? "voice-btn-on" : "voice-btn-muted"}`}
          onClick={onToggleVoice}
          aria-label={voiceEnabled ? "Mute voice alerts" : "Unmute voice alerts"}
        >
          {voiceEnabled ? "🔊 Voice: ON" : "🔇 Voice: MUTED"}
        </button>
        <button
          type="button"
          className="voice-action-btn voice-btn-replay"
          onClick={() => onReplayVoice?.()}
          aria-label="Replay last voice alert"
        >
          🔁 Replay Voice
        </button>
        <button
          type="button"
          className="voice-action-btn voice-btn-test"
          onClick={() => onTestVoice?.()}
          aria-label="Test voice announcement"
        >
          🧪 Test Voice
        </button>
      </div>

      <div className="camera-frame" aria-label="Camera preview">
        <video ref={videoRef} autoPlay muted playsInline aria-label="Live webcam feed" />
        {cameraActive && (
          <LiveDetectionOverlay
            videoRef={videoRef}
            detections={liveDetections}
            knownObjectNames={knownObjectNames}
            cameraActive={cameraActive}
          />
        )}
        {cameraActive && (
          <div className="live-detection-hud" aria-live="polite">
            <span className="live-hud-badge">
              🎯 {liveDetections.length} Object{liveDetections.length === 1 ? "" : "s"} Detected
            </span>
            {lastScanTime && (
              <span className="live-hud-time">
                ⏱️ {lastScanTime}
              </span>
            )}
            <span className={`live-hud-status live-status-${monitoringState}`}>
              {monitoringState === "active" ? "🟢 Aligned" : monitoringState === "moved" ? "⚠️ Moved" : "⏸️ Paused"}
            </span>
          </div>
        )}
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
          {cameraActive ? (
            <button
              className="button button-secondary"
              onClick={onStop}
              aria-label="Stop monitoring camera"
            >
              ⏹ Stop {baselineDetectionCount ? "Monitoring" : "Camera"}
            </button>
          ) : cameraStarting ? (
            <button
              className="button button-secondary"
              disabled={cameraStartCanceled}
              onClick={onStop}
              aria-label="Cancel camera startup"
            >
              {cameraStartCanceled ? "Canceling camera start…" : "Cancel camera start"}
            </button>
          ) : (
            <button
              className="button button-secondary"
              disabled={baselineLoading}
              onClick={onStart}
              aria-label="Start monitoring camera"
            >
              {baselineDetectionCount ? "▶ Start Monitoring" : "▶ Start Webcam"}
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

        <button
          className="compare-button"
          disabled={!canCompareSavedLayouts}
          onClick={onShowComparison}
          aria-label="Compare saved BEFORE and AFTER layouts"
        >
          🔍 Compare saved BEFORE &amp; AFTER
        </button>
      </div>

      <canvas className="capture-canvas" ref={canvasRef} aria-hidden="true" />
    </div>
  );
}
