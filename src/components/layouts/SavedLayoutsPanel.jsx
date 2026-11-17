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
  videoRef,
  onLayoutSaved,
  onLayoutActivated,
  beforeLayout,
  afterLayout,
  onComparisonLayoutSaved,
  onStartNewComparison,
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
    if (
      !cameraActive
      || !video
      || video.readyState < HTMLMediaElement.HAVE_CURRENT_DATA
      || video.videoWidth === 0
    ) {
      setActionError("Wait for the live camera preview before saving a new layout.");
      return;
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
    if (
      !cameraActive
      || !video
      || video.readyState < HTMLMediaElement.HAVE_CURRENT_DATA
      || video.videoWidth === 0
    ) {
      setActionError("Wait for the live camera preview before saving a comparison layout.");
      return;
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
        <h3>Before &amp; After capture</h3>
        {hasBeforeLayout && hasAfterLayout && (
          <button
            className="layout-refresh-button"
            disabled={busyAction !== ""}
            onClick={onStartNewComparison}
            type="button"
          >
            Start another comparison
          </button>
        )}
      </div>
      <p className="layout-help-text">
        Save BEFORE, change the room arrangement, then save AFTER. These captures are stored independently and do not replace the active monitoring baseline.
      </p>
      <div className="layout-save-form">
        <div className="room-field">
          <span>Original arrangement</span>
          <p className="layout-help-text">
            {hasBeforeLayout ? `Saved as layout ${beforeLayout.id}.` : "Capture this before changing the room."}
          </p>
        </div>
        <button
          className="button button-primary layout-save-button"
          disabled={!roomName.trim() || !cameraActive || hasBeforeLayout || busyAction !== ""}
          onClick={() => void handleSaveComparisonLayout("before")}
          type="button"
        >
          {busyAction === "save-before" ? "Saving BEFORE..." : "Capture BEFORE layout"}
        </button>
      </div>
      <div className="layout-save-form">
        <div className="room-field">
          <span>Updated arrangement</span>
          <p className="layout-help-text">
            {hasAfterLayout ? `Saved as layout ${afterLayout.id}.` : "Capture this after changing the room."}
          </p>
        </div>
        <button
          className="button button-primary layout-save-button"
          disabled={!roomName.trim() || !cameraActive || !hasBeforeLayout || hasAfterLayout || busyAction !== ""}
          onClick={() => void handleSaveComparisonLayout("after")}
          type="button"
        >
          {busyAction === "save-after" ? "Saving AFTER..." : "Capture AFTER layout"}
        </button>
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
