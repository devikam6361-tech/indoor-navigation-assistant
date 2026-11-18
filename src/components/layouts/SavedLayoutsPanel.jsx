import { useEffect, useRef, useState } from "react";
import {
  activateLayout,
  createLayout,
  deleteLayout,
  fetchLayouts,
} from "../../utils/apiClient.js";
import { captureJpegFromVideo } from "../../utils/imageCapture.js";
import { formatDate } from "../../utils/formatters.js";

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
    <div className="detection-results" aria-label={`${label} detection results`}>
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

export default function SavedLayoutsPanel({
  roomName,
  cameraId,
  cameraActive,
  cameraStarting = false,
  videoRef,
  onLayoutSaved,
  onLayoutActivated,
  beforeLayout,
  afterLayout,
  onComparisonLayoutSaved,
  onStartNewComparison,
  onStartCamera,
}) {
  const [layouts, setLayouts] = useState([]);
  const [layoutName, setLayoutName] = useState("");
  const [loading, setLoading] = useState(Boolean(roomName.trim()));
  const [busyAction, setBusyAction] = useState("");
  const [listError, setListError] = useState("");
  const [actionError, setActionError] = useState("");
  const [success, setSuccess] = useState("");
  const [previewId, setPreviewId] = useState(null);
  const mutationInFlight = useRef(false);
  const mounted = useRef(false);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    if (!roomName.trim()) return () => controller.abort();
    fetchLayouts(roomName, cameraId, { signal: controller.signal })
      .then(({ layouts: result }) => {
        if (!controller.signal.aborted) {
          setLayouts(result);
        }
      })
      .catch((error) => {
        if (!controller.signal.aborted) {
          setListError(error.message);
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) {
          setLoading(false);
        }
      });

    return () => controller.abort();
  }, [roomName, cameraId]);

  async function refreshLayouts() {
    const { layouts: refreshedLayouts } = await fetchLayouts(roomName, cameraId);
    if (mounted.current) setLayouts(refreshedLayouts);
  }

  async function reloadLayouts() {
    setLoading(true);
    setListError("");
    try {
      await refreshLayouts();
    } catch (error) {
      if (mounted.current) setListError(error.message);
    } finally {
      if (mounted.current) setLoading(false);
    }
  }

  async function handleSave(event) {
    event.preventDefault();
    if (mutationInFlight.current) return;
    if (!roomName.trim()) {
      setActionError("Select or enter a room before saving a layout.");
      return;
    }
    if (!layoutName.trim()) {
      setActionError("Enter a name for this layout.");
      return;
    }
    const video = videoRef.current;
    if (!cameraActive) {
      setActionError("Start the camera before saving an active layout.");
      return;
    }
    if (!video) {
      setActionError("Wait for the live camera preview before saving a new layout.");
      return;
    }

    if (video.readyState < HTMLMediaElement.HAVE_CURRENT_DATA || video.videoWidth === 0) {
      try {
        await new Promise((resolve, reject) => {
          if (video.readyState >= HTMLMediaElement.HAVE_CURRENT_DATA && video.videoWidth > 0) {
            resolve();
            return;
          }
          const checkTimer = setInterval(() => {
            if (video.readyState >= HTMLMediaElement.HAVE_CURRENT_DATA && video.videoWidth > 0) {
              clearInterval(checkTimer);
              clearTimeout(timeoutTimer);
              resolve();
            }
          }, 100);
          const timeoutTimer = setTimeout(() => {
            clearInterval(checkTimer);
            reject(new Error("Timeout waiting for preview frames."));
          }, 2500);
        });
      } catch {
        setActionError("Wait for the live camera preview before saving a new layout.");
        return;
      }
    }

    mutationInFlight.current = true;
    setBusyAction("save");
    setActionError("");
    setSuccess("");
    try {
      const image = await captureJpegFromVideo(video, 0.82);
      const { layout } = await createLayout({
        roomName,
        cameraId,
        layoutName: layoutName.trim(),
        image,
      });
      if (!mounted.current) return;
      setLayoutName("");
      setSuccess(`Saved “${layout.layout_name}” and made it the active layout.`);
      onLayoutSaved(layout);
      try {
        await refreshLayouts();
      } catch (error) {
        setActionError(`The layout was saved, but the list could not be refreshed: ${error.message}`);
      }
    } catch (error) {
      if (mounted.current) {
        setActionError(`Could not save layout: ${error.message}`);
      }
    } finally {
      mutationInFlight.current = false;
      setBusyAction("");
    }
  }

  async function handleSaveComparisonLayout(stage) {
    if (mutationInFlight.current) return;
    if (!roomName.trim()) {
      setActionError("Select or enter a room before saving a comparison layout.");
      return;
    }

    const matchesCurrentScope = (layout) =>
      layout
      && layout.room_name.toLowerCase() === roomName.trim().toLowerCase()
      && layout.camera_id === cameraId;
    const hasBefore = matchesCurrentScope(beforeLayout);
    const hasAfter = matchesCurrentScope(afterLayout);
    if (stage === "before" && hasBefore) {
      setActionError("A BEFORE layout is already saved for this comparison.");
      return;
    }
    if (stage === "after" && !hasBefore) {
      setActionError("Save the BEFORE layout before capturing the AFTER layout.");
      return;
    }
    if (stage === "after" && hasAfter) {
      setActionError("An AFTER layout is already saved for this comparison.");
      return;
    }

    const video = videoRef.current;
    if (!cameraActive) {
      setActionError("Start the camera before capturing a comparison layout.");
      return;
    }
    if (!video) {
      setActionError("Wait for the live camera preview before saving a comparison layout.");
      return;
    }

    if (video.readyState < HTMLMediaElement.HAVE_CURRENT_DATA || video.videoWidth === 0) {
      try {
        await new Promise((resolve, reject) => {
          if (video.readyState >= HTMLMediaElement.HAVE_CURRENT_DATA && video.videoWidth > 0) {
            resolve();
            return;
          }
          const checkTimer = setInterval(() => {
            if (video.readyState >= HTMLMediaElement.HAVE_CURRENT_DATA && video.videoWidth > 0) {
              clearInterval(checkTimer);
              clearTimeout(timeoutTimer);
              resolve();
            }
          }, 100);
          const timeoutTimer = setTimeout(() => {
            clearInterval(checkTimer);
            reject(new Error("Timeout waiting for preview frames."));
          }, 2500);
        });
      } catch {
        setActionError("Wait for the live camera preview before saving a comparison layout.");
        return;
      }
    }

    mutationInFlight.current = true;
    setBusyAction(`save-${stage}`);
    setActionError("");
    setSuccess("");
    try {
      const image = await captureJpegFromVideo(video, 0.82);
      const layoutName = stage === "before"
        ? "Before – Original Layout"
        : "After – Updated Layout";
      const { layout } = await createLayout({
        roomName,
        cameraId,
        layoutName,
        image,
        activate: false,
      });
      if (!mounted.current) return;
      onComparisonLayoutSaved(stage, layout);
      setSuccess(
        `${stage === "before" ? "BEFORE" : "AFTER"} layout saved to history without changing the active baseline.`,
      );
      try {
        await refreshLayouts();
      } catch (error) {
        setActionError(`The comparison layout was saved, but the history list could not be refreshed: ${error.message}`);
      }
    } catch (error) {
      if (mounted.current) {
        setActionError(`Could not save ${stage === "before" ? "BEFORE" : "AFTER"} layout: ${error.message}`);
      }
    } finally {
      mutationInFlight.current = false;
      setBusyAction("");
    }
  }

  async function handleActivate(layout) {
    if (mutationInFlight.current || layout.deleted_at || layout.is_active) return;
    mutationInFlight.current = true;
    setBusyAction(`activate-${layout.id}`);
    setActionError("");
    setSuccess("");
    try {
      const { layout: activatedLayout } = await activateLayout(layout.id, roomName, cameraId);
      if (!mounted.current) return;
      onLayoutActivated(activatedLayout);
      setSuccess(`Restored “${activatedLayout.layout_name}” as the active layout.`);
      try {
        await refreshLayouts();
      } catch (error) {
        setActionError(`The layout was restored, but the list could not be refreshed: ${error.message}`);
      }
    } catch (error) {
      if (mounted.current) {
        setActionError(`Could not restore layout: ${error.message}`);
      }
    } finally {
      mutationInFlight.current = false;
      setBusyAction("");
    }
  }

  async function handleDelete(layout) {
    if (mutationInFlight.current || layout.deleted_at || layout.is_active) return;
    if (!window.confirm(`Move “${layout.layout_name}” to deleted layouts? It will not be physically removed.`)) {
      return;
    }

    mutationInFlight.current = true;
    setBusyAction(`delete-${layout.id}`);
    setActionError("");
    setSuccess("");
    try {
      const result = await deleteLayout(layout.id, roomName, cameraId);
      if (!mounted.current) return;
      setSuccess(`“${layout.layout_name}” was moved to deleted layouts.`);
      setLayouts((current) =>
        current.map((item) =>
          item.id === layout.id ? { ...item, deleted_at: result.deleted_at, is_active: false } : item,
        ),
      );
      try {
        await refreshLayouts();
      } catch (error) {
        setActionError(`The layout was deleted, but the list could not be refreshed: ${error.message}`);
      }
    } catch (error) {
      if (mounted.current) {
        setActionError(`Could not delete layout: ${error.message}`);
      }
    } finally {
      mutationInFlight.current = false;
      setBusyAction("");
    }
  }

  const availableCount = layouts.filter((layout) => !layout.deleted_at).length;
  const selectedComparisonIds = new Set(
    [beforeLayout?.id, afterLayout?.id].filter((id) => id != null),
  );
  const comparisonScopeMatches = (layout) =>
    layout
    && layout.room_name.toLowerCase() === roomName.trim().toLowerCase()
    && layout.camera_id === cameraId;
  const hasBeforeLayout = comparisonScopeMatches(beforeLayout);
  const hasAfterLayout = comparisonScopeMatches(afterLayout);

  return (
    <section className="panel saved-layouts-panel" aria-labelledby="saved-layouts-heading">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">LAYOUT HISTORY</p>
          <h2 id="saved-layouts-heading">Saved layouts</h2>
        </div>
        <span className="saved-layout-scope">
          {roomName.trim() || "No room selected"} · Camera {cameraId}
        </span>
      </div>

      <form className="layout-save-form" onSubmit={handleSave}>
        <label className="room-field" htmlFor="saved-layout-name">
          <span>New layout name</span>
          <input
            id="saved-layout-name"
            autoComplete="off"
            maxLength={80}
            onChange={(event) => setLayoutName(event.target.value)}
            placeholder="e.g. After furniture rearrangement"
            value={layoutName}
          />
        </label>
        <button
          className="button button-primary layout-save-button"
          disabled={!roomName.trim() || !cameraActive || !layoutName.trim() || busyAction !== ""}
          type="submit"
        >
          {busyAction === "save" ? "Saving active layout..." : "Save current view as ACTIVE layout"}
        </button>
        <p className="layout-help-text">
          This option changes the active monitoring baseline. Use the separate BEFORE/AFTER controls below for comparisons.
        </p>
        {!cameraActive && (
          <p className="layout-help-text">Start the webcam to capture and save a new layout.</p>
        )}
      </form>

      <div className="layout-list-heading">
        <div className="heading-with-sub">
          <h3>Before &amp; After Capture</h3>
          <p className="layout-help-text">
            Capture BEFORE, rearrange room objects, then capture AFTER. Stored independently without replacing the active baseline.
          </p>
        </div>
        {hasBeforeLayout && hasAfterLayout && (
          <button
            className="layout-refresh-button layout-new-comparison-btn"
            disabled={busyAction !== ""}
            onClick={onStartNewComparison}
            type="button"
          >
            ↺ Start Another Comparison
          </button>
        )}
      </div>

      <div className="comparison-capture-grid">
        {/* BEFORE CAPTURE CARD */}
        <div className={`comparison-capture-card before-card ${hasBeforeLayout ? "is-captured" : ""}`}>
          <div className="capture-card-header">
            <span className="capture-card-badge before-badge">BEFORE</span>
            <span className="capture-card-title">Original Room Layout</span>
            {hasBeforeLayout && <span className="capture-status-pill">✓ Saved</span>}
          </div>

          <div className="capture-card-body">
            {hasBeforeLayout && beforeLayout?.image_data_url ? (
              <div className="capture-preview-box">
                <img
                  src={beforeLayout.image_data_url}
                  alt="Original layout before"
                  className="capture-thumb-img"
                />
                <div className="capture-info">
                  <strong className="capture-layout-name">{beforeLayout.layout_name || "Before – Original Layout"}</strong>
                  <span className="capture-meta-date">
                    Captured {beforeLayout.captured_at ? formatDate(beforeLayout.captured_at) : "Saved"}
                  </span>
                  <span className="capture-meta-id">Layout #{beforeLayout.id}</span>
                </div>
              </div>
            ) : (
              <div className="capture-empty-box">
                <span className="capture-icon">📷</span>
                <p className="capture-prompt">
                  {!cameraActive
                    ? "Camera is off. Start the camera to view the room and capture the original layout."
                    : "Webcam is live. Point it at the room and capture the original layout."}
                </p>
              </div>
            )}
          </div>

          <div className="capture-card-footer">
            {!cameraActive ? (
              <button
                className="button button-crimson layout-save-button"
                disabled={cameraStarting || busyAction !== ""}
                onClick={() => onStartCamera?.()}
                type="button"
              >
                {cameraStarting ? "⏳ Starting Camera..." : "📷 Start Camera to Capture"}
              </button>
            ) : (
              <button
                className="button button-secondary layout-save-button"
                disabled={!roomName.trim() || !cameraActive || hasBeforeLayout || busyAction !== ""}
                onClick={() => void handleSaveComparisonLayout("before")}
                type="button"
              >
                {busyAction === "save-before"
                  ? "Saving BEFORE..."
                  : hasBeforeLayout
                    ? "✓ BEFORE Captured"
                    : "Capture BEFORE Layout"}
              </button>
            )}
          </div>
        </div>

        {/* AFTER CAPTURE CARD */}
        <div className={`comparison-capture-card after-card ${hasAfterLayout ? "is-captured" : ""}`}>
          <div className="capture-card-header">
            <span className="capture-card-badge after-badge">AFTER</span>
            <span className="capture-card-title">Updated Room Layout</span>
            {hasAfterLayout && <span className="capture-status-pill">✓ Saved</span>}
          </div>

          <div className="capture-card-body">
            {hasAfterLayout && afterLayout?.image_data_url ? (
              <div className="capture-preview-box">
                <img
                  src={afterLayout.image_data_url}
                  alt="Updated layout after"
                  className="capture-thumb-img"
                />
                <div className="capture-info">
                  <strong className="capture-layout-name">{afterLayout.layout_name || "After – Updated Layout"}</strong>
                  <span className="capture-meta-date">
                    Captured {afterLayout.captured_at ? formatDate(afterLayout.captured_at) : "Saved"}
                  </span>
                  <span className="capture-meta-id">Layout #{afterLayout.id}</span>
                </div>
              </div>
            ) : (
              <div className="capture-empty-box">
                <span className="capture-icon">🔄</span>
                <p className="capture-prompt">
                  {!hasBeforeLayout
                    ? "Capture BEFORE layout first, then rearrange items."
                    : !cameraActive
                    ? "Start the camera to capture the updated layout."
                    : "Rearrange room objects, then capture this updated layout."}
                </p>
              </div>
            )}
          </div>

          <div className="capture-card-footer">
            <button
              className="button button-crimson layout-save-button"
              disabled={!roomName.trim() || !cameraActive || !hasBeforeLayout || hasAfterLayout || busyAction !== ""}
              onClick={() => void handleSaveComparisonLayout("after")}
              type="button"
            >
              {busyAction === "save-after"
                ? "Saving AFTER..."
                : hasAfterLayout
                  ? "✓ AFTER Captured"
                  : "Capture AFTER Layout"}
            </button>
          </div>
        </div>
      </div>

      {success && <p className="layout-message layout-success" role="status" aria-live="polite">{success}</p>}
      {actionError && <p className="layout-message layout-error" role="alert">{actionError}</p>}

      <div className="layout-list-heading">
        <h3>Room history</h3>
        <button
          className="layout-refresh-button"
          disabled={loading || busyAction !== "" || !roomName.trim()}
          onClick={() => void reloadLayouts()}
          type="button"
        >
          Refresh layouts
        </button>
      </div>

      {loading && <p className="empty-state" role="status">Loading saved layouts...</p>}
      {!loading && listError && (
        <p className="layout-message layout-error" role="alert">
          Could not load layouts: {listError}
        </p>
      )}
      {!loading && !listError && layouts.length === 0 && (
        <p className="empty-state">No saved layouts for this room and camera yet.</p>
      )}
      {!loading && !listError && layouts.length > 0 && (
        <ul className="saved-layout-list" aria-label={`Saved layouts for ${roomName}`}>
          {layouts.map((layout) => {
            const isDeleted = Boolean(layout.deleted_at);
            const isLastAvailable = !isDeleted && availableCount <= 1;
            const previewExpanded = previewId === layout.id;
            const isSelectedForComparison = selectedComparisonIds.has(layout.id);
            const detectionResult = getDetectionResults(layout);
            return (
              <li className={`saved-layout-card ${isDeleted ? "layout-deleted" : ""}`} key={layout.id}>
                <div className="saved-layout-details">
                  <div className="saved-layout-title-row">
                    <h4>{layout.layout_name}</h4>
                    <span className={`layout-status ${layout.is_active ? "layout-status-active" : ""}`}>
                      {isDeleted ? "Deleted" : layout.is_active ? "Active" : "Inactive"}
                    </span>
                  </div>
                  <p>
                    Captured{" "}
                    <time dateTime={layout.captured_at}>{formatDate(layout.captured_at)}</time>
                  </p>
                  {isDeleted && (
                    <p>
                      Deleted{" "}
                      <time dateTime={layout.deleted_at}>{formatDate(layout.deleted_at)}</time>
                    </p>
                  )}
                  <DetectionResults
                    result={detectionResult}
                    label={`${layout.layout_name} in ${layout.room_name}`}
                  />
                  <div className="saved-layout-actions">
                    <button
                      aria-controls={`layout-preview-${layout.id}`}
                      aria-expanded={previewExpanded}
                      aria-label={`${previewExpanded ? "Hide" : "Preview"} ${layout.layout_name} image`}
                      className="layout-action-button"
                      onClick={() => setPreviewId(previewExpanded ? null : layout.id)}
                      type="button"
                    >
                      {previewExpanded ? "Hide preview" : "Preview image"}
                    </button>
                    <button
                      className="layout-action-button"
                      disabled={busyAction !== "" || isDeleted || layout.is_active}
                      onClick={() => void handleActivate(layout)}
                      type="button"
                    >
                      {busyAction === `activate-${layout.id}`
                        ? "Restoring..."
                        : layout.is_active
                          ? "Currently active"
                          : isDeleted
                            ? "Deleted layouts cannot be restored"
                            : "Restore layout"}
                    </button>
                    <button
                      className="layout-action-button"
                      disabled={busyAction !== "" || isDeleted}
                      onClick={() => onComparisonLayoutSaved("before", layout)}
                      type="button"
                      title="Set as BEFORE reference layout"
                    >
                      {beforeLayout?.id === layout.id ? "✓ In BEFORE" : "Set as BEFORE"}
                    </button>
                    <button
                      className="layout-action-button"
                      disabled={busyAction !== "" || isDeleted}
                      onClick={() => onComparisonLayoutSaved("after", layout)}
                      type="button"
                      title="Set as AFTER comparison layout"
                    >
                      {afterLayout?.id === layout.id ? "✓ In AFTER" : "Set as AFTER"}
                    </button>
                    <button
                      className="layout-action-button layout-delete-button"
                      disabled={busyAction !== "" || isDeleted || layout.is_active || isLastAvailable || isSelectedForComparison}
                      onClick={() => void handleDelete(layout)}
                      type="button"
                    >
                      {busyAction === `delete-${layout.id}` ? "Deleting..." : "Delete"}
                    </button>
                  </div>
                  {layout.is_active && <p className="layout-help-text">The active layout cannot be deleted.</p>}
                  {!layout.is_active && isLastAvailable && (
                    <p className="layout-help-text">The last available layout cannot be deleted.</p>
                  )}
                  {isSelectedForComparison && (
                    <p className="layout-help-text">A layout selected for the current comparison cannot be deleted.</p>
                  )}
                  {previewExpanded && (
                    <div className="saved-layout-preview" id={`layout-preview-${layout.id}`}>
                      <img
                        alt={`Saved camera view for ${layout.layout_name} in ${layout.room_name}`}
                        src={layout.image_data_url}
                      />
                    </div>
                  )}
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
