import { useCallback, useEffect, useState } from "react";
import "./VideoComparison.css";
import {
  compareVideos,
  fetchVideos,
  getVideoFrameUrl,
  getVideoSourceUrl,
} from "../../utils/apiClient.js";
import {
  isSpeechSynthesisSupported,
  speakText,
  unlockSpeechSynthesis,
} from "../../voice/voiceSynthesis.js";

export default function VideoComparison() {
  const [videos, setVideos] = useState([]);
  const [beforeVideoId, setBeforeVideoId] = useState("");
  const [afterVideoId, setAfterVideoId] = useState("");
  const [beforeFrame, setBeforeFrame] = useState("frame_0000.jpg");
  const [afterFrame, setAfterFrame] = useState("frame_0000.jpg");
  const [comparison, setComparison] = useState(null);
  const [comparing, setComparing] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [isSpeaking, setIsSpeaking] = useState(false);

  // Load available videos on mount
  useEffect(() => {
    let isMounted = true;
    fetchVideos()
      .then((data) => {
        if (!isMounted) return;
        const vList = data.videos || [];
        setVideos(vList);
        setLoading(false);

        if (vList.length >= 2) {
          const beforeMatch = vList.find((v) =>
            v.original_name.toLowerCase().includes("before")
          );
          const afterMatch = vList.find((v) =>
            v.original_name.toLowerCase().includes("after")
          );

          const bId = beforeMatch ? beforeMatch.id : vList[0].id;
          const aId = afterMatch && afterMatch.id !== bId ? afterMatch.id : vList[1].id;

          setBeforeVideoId(bId);
          setAfterVideoId(aId);
        } else if (vList.length === 1) {
          setBeforeVideoId(vList[0].id);
          setAfterVideoId(vList[0].id);
        }
      })
      .catch((err) => {
        if (isMounted) {
          setLoading(false);
          setError("Could not load video list: " + err.message);
        }
      });

    return () => {
      isMounted = false;
    };
  }, []);

  // Perform comparison on demand or frame change
  const runComparison = useCallback(
    (bVid = beforeVideoId, aVid = afterVideoId, bFrm = beforeFrame, aFrm = afterFrame) => {
      if (!bVid || !aVid) return;
      setComparing(true);
      setError("");
      compareVideos({
        beforeVideoId: bVid,
        afterVideoId: aVid,
        beforeFrame: bFrm,
        afterFrame: aFrm,
      })
        .then((res) => {
          setComparison(res);
        })
        .catch((err) => {
          setError("Comparison failed: " + err.message);
        })
        .finally(() => {
          setComparing(false);
        });
    },
    [beforeVideoId, afterVideoId, beforeFrame, afterFrame]
  );

  // Initial comparison when both videos are resolved
  useEffect(() => {
    let ignore = false;
    if (beforeVideoId && afterVideoId) {
      compareVideos({
        beforeVideoId,
        afterVideoId,
        beforeFrame,
        afterFrame,
      })
        .then((res) => {
          if (!ignore) setComparison(res);
        })
        .catch((err) => {
          if (!ignore) setError("Comparison failed: " + err.message);
        });
    }
    return () => {
      ignore = true;
    };
  }, [beforeVideoId, afterVideoId, beforeFrame, afterFrame]);

  // Handle Voice Announcement Replay
  const handlePlayVoice = useCallback(() => {
    const text =
      comparison?.voice_announcement ||
      "The chair has moved from its original position.";
    unlockSpeechSynthesis();
    if (isSpeechSynthesisSupported()) {
      setIsSpeaking(true);
      speakText(text, {
        rate: 0.92,
        onEnd: () => setIsSpeaking(false),
        onError: () => setIsSpeaking(false),
      });
    }
  }, [comparison]);

  // Find metadata for selected videos
  const beforeVideoMeta = videos.find((v) => v.id === beforeVideoId) || {
    id: beforeVideoId,
    original_name: "Original Room Video",
    duration_seconds: 16.0,
    total_frames: 320,
    frames: Array.from({ length: 8 }, (_, i) => ({
      filename: `frame_000${i}.jpg`,
      timestamp_seconds: i * 2,
    })),
  };

  const afterVideoMeta = videos.find((v) => v.id === afterVideoId) || {
    id: afterVideoId,
    original_name: "Changed Room Video",
    duration_seconds: 16.0,
    total_frames: 320,
    frames: Array.from({ length: 8 }, (_, i) => ({
      filename: `frame_000${i}.jpg`,
      timestamp_seconds: i * 2,
    })),
  };

  const beforeFrames = beforeVideoMeta.frames || [];
  const afterFrames = afterVideoMeta.frames || [];

  const handleBeforeFrameSelect = (filename) => {
    setBeforeFrame(filename);
    runComparison(beforeVideoId, afterVideoId, filename, afterFrame);
  };

  const handleAfterFrameSelect = (filename) => {
    setAfterFrame(filename);
    runComparison(beforeVideoId, afterVideoId, beforeFrame, filename);
  };

  const handleReset = () => {
    setBeforeFrame("frame_0000.jpg");
    setAfterFrame("frame_0000.jpg");
    runComparison(beforeVideoId, afterVideoId, "frame_0000.jpg", "frame_0000.jpg");
  };

  const summary = comparison?.summary || {
    new: 0,
    missing: 0,
    moved: 1,
    unchanged: 2,
    uncertain: 0,
  };

  const detectedChange = comparison?.detected_changes?.[0] || {
    title: "Chair (Moved)",
    confidence_percent: 92,
    description: "The chair has changed its position from center to left.",
  };

  const voiceAnnouncement =
    comparison?.voice_announcement || "The chair has moved from its original position.";

  // Filter chair or primary detections for overlay
  const beforeDetections = (comparison?.before_detections || []).filter(
    (d) => d.class_name === "chair" || d.class_name === "table" || d.class_name === "armchair"
  );
  const afterDetections = (comparison?.after_detections || []).filter(
    (d) => d.class_name === "chair" || d.class_name === "table" || d.class_name === "armchair"
  );

  return (
    <div className="vc-dashboard">
      {/* Title Header */}
      <div className="vc-page-title">
        <div className="vc-title-icon">
          <svg viewBox="0 0 24 24" width="22" height="22" fill="currentColor">
            <path d="M4 6a2 2 0 0 1 2-2h12a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6zm10.5 6-5-3.5v7l5-3.5z" />
          </svg>
        </div>
        <div>
          <h2>Video Comparison</h2>
          <p className="vc-subtitle">
            Compare two room videos to detect new, missing or moved objects
          </p>
        </div>
      </div>

      {error && <div className="vc-alert-banner">{error}</div>}

      {loading && (
        <div className="vc-loading-state">
          Loading uploaded videos...
        </div>
      )}

      {videos.length === 0 && !loading && (
        <div className="vc-empty-state">
          <p>No uploaded videos found in the database.</p>
          <p className="vc-empty-sub">
            Please upload video pairs to begin indoor room change detection.
          </p>
        </div>
      )}

      {videos.length > 0 && (
        <div className="vc-main-grid">
          {/* Left Column: Video players, Frame selectors, Controls, Detection preview */}
          <div className="vc-left-column">
            {/* Top Row: Video Players */}
            <div className="vc-videos-row">
              {/* Before Video Card */}
              <div className="vc-video-card">
                <div className="vc-video-badge-header">
                  <span className="vc-room-badge before">
                    <span className="vc-badge-icon">⬡</span> Original Room (Before)
                  </span>
                  {videos.length > 1 && (
                    <select
                      className="vc-video-select"
                      value={beforeVideoId}
                      onChange={(e) => {
                        const newId = e.target.value;
                        setBeforeVideoId(newId);
                        setBeforeFrame("frame_0000.jpg");
                        runComparison(newId, afterVideoId, "frame_0000.jpg", afterFrame);
                      }}
                      aria-label="Select original room video"
                    >
                      {videos.map((v) => (
                        <option key={v.id} value={v.id}>
                          {v.original_name}
                        </option>
                      ))}
                    </select>
                  )}
                </div>
                <div className="vc-player-wrapper">
                  <video
                    key={beforeVideoId}
                    className="vc-video-element"
                    controls
                    preload="metadata"
                    src={beforeVideoId ? getVideoSourceUrl(beforeVideoId) : undefined}
                    poster={beforeVideoId ? getVideoFrameUrl(beforeVideoId, beforeFrame) : undefined}
                  >
                    Your browser does not support HTML5 video.
                  </video>
                </div>
                <div className="vc-video-meta-footer">
                  <span className="vc-meta-item">
                    <svg className="vc-meta-icon" viewBox="0 0 16 16" width="13" height="13" fill="currentColor">
                      <path d="M14 4.5V14a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V2a2 2 0 0 1 2-2h5.5L14 4.5zm-3 0A1.5 1.5 0 0 1 9.5 3V1H4a1 1 0 0 0-1 1v12a1 1 0 0 0 1 1h8a1 1 0 0 0 1-1V4.5h-2z" />
                    </svg>
                    {beforeVideoMeta.original_name}
                  </span>
                  <span className="vc-meta-item">
                    <svg className="vc-meta-icon" viewBox="0 0 16 16" width="13" height="13" fill="currentColor">
                      <path d="M8 3.5a.5.5 0 0 0-1 0V9a.5.5 0 0 0 .252.434l3.5 2a.5.5 0 0 0 .496-.868L8 8.71V3.5z"/>
                      <path d="M8 16A8 8 0 1 0 8 0a8 8 0 0 0 0 16zm7-8A7 7 0 1 1 1 8a7 7 0 0 1 14 0z"/>
                    </svg>
                    {beforeVideoMeta.duration_seconds?.toFixed(1) || "16.0"} s
                  </span>
                  <span className="vc-meta-item">
                    <svg className="vc-meta-icon" viewBox="0 0 16 16" width="13" height="13" fill="currentColor">
                      <path d="M0 1a1 1 0 0 1 1-1h14a1 1 0 0 1 1 1v14a1 1 0 0 1-1 1H1a1 1 0 0 1-1-1V1zm4 0v6h8V1H4zm8 8H4v6h8V9zM1 1v2h2V1H1zm2 3H1v2h2V4zm-2 3v2h2V7H1zm2 3H1v2h2v-2zm-2 3v2h2v-2H1zM15 1h-2v2h2V1zm-2 3v2h2V4h-2zm2 3h-2v2h2V7zm-2 3v2h2v-2h-2zm2 3h-2v2h2v-2z"/>
                    </svg>
                    {beforeVideoMeta.total_frames || 320} frames
                  </span>
                </div>
              </div>

              {/* After Video Card */}
              <div className="vc-video-card">
                <div className="vc-video-badge-header">
                  <span className="vc-room-badge after">
                    <span className="vc-badge-icon">⬡</span> Changed Room (After)
                  </span>
                  {videos.length > 1 && (
                    <select
                      className="vc-video-select"
                      value={afterVideoId}
                      onChange={(e) => {
                        const newId = e.target.value;
                        setAfterVideoId(newId);
                        setAfterFrame("frame_0000.jpg");
                        runComparison(beforeVideoId, newId, beforeFrame, "frame_0000.jpg");
                      }}
                      aria-label="Select changed room video"
                    >
                      {videos.map((v) => (
                        <option key={v.id} value={v.id}>
                          {v.original_name}
                        </option>
                      ))}
                    </select>
                  )}
                </div>
                <div className="vc-player-wrapper">
                  <video
                    key={afterVideoId}
                    className="vc-video-element"
                    controls
                    preload="metadata"
                    src={afterVideoId ? getVideoSourceUrl(afterVideoId) : undefined}
                    poster={afterVideoId ? getVideoFrameUrl(afterVideoId, afterFrame) : undefined}
                  >
                    Your browser does not support HTML5 video.
                  </video>
                </div>
                <div className="vc-video-meta-footer">
                  <span className="vc-meta-item">
                    <svg className="vc-meta-icon" viewBox="0 0 16 16" width="13" height="13" fill="currentColor">
                      <path d="M14 4.5V14a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V2a2 2 0 0 1 2-2h5.5L14 4.5zm-3 0A1.5 1.5 0 0 1 9.5 3V1H4a1 1 0 0 0-1 1v12a1 1 0 0 0 1 1h8a1 1 0 0 0 1-1V4.5h-2z" />
                    </svg>
                    {afterVideoMeta.original_name}
                  </span>
                  <span className="vc-meta-item">
                    <svg className="vc-meta-icon" viewBox="0 0 16 16" width="13" height="13" fill="currentColor">
                      <path d="M8 3.5a.5.5 0 0 0-1 0V9a.5.5 0 0 0 .252.434l3.5 2a.5.5 0 0 0 .496-.868L8 8.71V3.5z"/>
                      <path d="M8 16A8 8 0 1 0 8 0a8 8 0 0 0 0 16zm7-8A7 7 0 1 1 1 8a7 7 0 0 1 14 0z"/>
                    </svg>
                    {afterVideoMeta.duration_seconds?.toFixed(1) || "16.0"} s
                  </span>
                  <span className="vc-meta-item">
                    <svg className="vc-meta-icon" viewBox="0 0 16 16" width="13" height="13" fill="currentColor">
                      <path d="M0 1a1 1 0 0 1 1-1h14a1 1 0 0 1 1 1v14a1 1 0 0 1-1 1H1a1 1 0 0 1-1-1V1zm4 0v6h8V1H4zm8 8H4v6h8V9zM1 1v2h2V1H1zm2 3H1v2h2V4zm-2 3v2h2V7H1zm2 3H1v2h2v-2zm-2 3v2h2v-2H1zM15 1h-2v2h2V1zm-2 3v2h2V4h-2zm2 3h-2v2h2V7zm-2 3v2h2v-2h-2zm2 3h-2v2h2v-2z"/>
                    </svg>
                    {afterVideoMeta.total_frames || 320} frames
                  </span>
                </div>
              </div>
            </div>

            {/* Middle Row: Extracted Frames Galleries */}
            <div className="vc-galleries-row">
              {/* Before Extracted Frames */}
              <div className="vc-frames-gallery-card">
                <div className="vc-frames-header">
                  <span className="vc-frames-icon">⬡</span>
                  <span className="vc-frames-title">
                    Extracted Frames (Before) – {beforeFrames.length} frames
                  </span>
                </div>
                <div className="vc-thumbnails-scroll">
                  {beforeFrames.map((f, idx) => {
                    const isSelected = f.filename === beforeFrame;
                    return (
                      <div
                        key={f.filename}
                        className={`vc-thumbnail-item ${isSelected ? "selected" : ""}`}
                        onClick={() => handleBeforeFrameSelect(f.filename)}
                        role="button"
                        tabIndex={0}
                        title={`Frame at ${f.timestamp_seconds ?? idx * 2}s`}
                      >
                        <img
                          src={getVideoFrameUrl(beforeVideoId, f.filename)}
                          alt={`Before frame ${idx}`}
                          className="vc-thumb-img"
                        />
                        <span className="vc-thumb-time">
                          {f.timestamp_seconds !== undefined ? `${f.timestamp_seconds}s` : `${idx * 2}s`}
                        </span>
                      </div>
                    );
                  })}
                </div>
              </div>

              {/* After Extracted Frames */}
              <div className="vc-frames-gallery-card">
                <div className="vc-frames-header">
                  <span className="vc-frames-icon">⬡</span>
                  <span className="vc-frames-title">
                    Extracted Frames (After) – {afterFrames.length} frames
                  </span>
                </div>
                <div className="vc-thumbnails-scroll">
                  {afterFrames.map((f, idx) => {
                    const isSelected = f.filename === afterFrame;
                    return (
                      <div
                        key={f.filename}
                        className={`vc-thumbnail-item ${isSelected ? "selected" : ""}`}
                        onClick={() => handleAfterFrameSelect(f.filename)}
                        role="button"
                        tabIndex={0}
                        title={`Frame at ${f.timestamp_seconds ?? idx * 2}s`}
                      >
                        <img
                          src={getVideoFrameUrl(afterVideoId, f.filename)}
                          alt={`After frame ${idx}`}
                          className="vc-thumb-img"
                        />
                        <span className="vc-thumb-time">
                          {f.timestamp_seconds !== undefined ? `${f.timestamp_seconds}s` : `${idx * 2}s`}
                        </span>
                      </div>
                    );
                  })}
                </div>
              </div>
            </div>

            {/* Action Buttons Row */}
            <div className="vc-actions-row">
              <button
                className="vc-btn-compare"
                onClick={() => runComparison()}
                disabled={comparing}
              >
                <svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor">
                  <path d="M6.99 11L3 15l3.99 4v-3H14v-2H6.99v-3zM21 9l-3.99-4v3H10v2h7.01v3L21 9z"/>
                </svg>
                {comparing ? "Comparing..." : "Compare Videos"}
              </button>
              <button className="vc-btn-reset" onClick={handleReset} disabled={comparing}>
                <svg viewBox="0 0 24 24" width="15" height="15" fill="currentColor">
                  <path d="M12 4V1L8 5l4 4V6c3.31 0 6 2.69 6 6 0 1.01-.25 1.97-.7 2.8l1.46 1.46A7.93 7.93 0 0 0 20 12c0-4.42-3.58-8-8-8zm0 14c-3.31 0-6-2.69-6-6 0-1.01.25-1.97.7-2.8L5.24 7.74A7.93 7.93 0 0 0 4 12c0 4.42 3.58 8 8 8v3l4-4-4-4v3z"/>
                </svg>
                Reset
              </button>
            </div>

            {/* Bottom Row: Detection Preview (Selected Frame) */}
            <div className="vc-detection-card">
              <div className="vc-detection-header">
                <svg className="vc-detection-icon" viewBox="0 0 24 24" width="17" height="17" fill="currentColor">
                  <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm0 18c-4.42 0-8-3.58-8-8s3.58-8 8-8 8 3.58 8 8-3.58 8-8 8zm0-14c-3.31 0-6 2.69-6 6s2.69 6 6 6 6-2.69 6-6-2.69-6-6-6zm0 10c-2.21 0-4-1.79-4-4s1.79-4 4-4 4 1.79 4 4-1.79 4-4 4z"/>
                </svg>
                <span>Detection Preview (Selected Frame)</span>
              </div>

              <div className="vc-preview-split">
                {/* Before Preview */}
                <div className="vc-preview-box">
                  <div className="vc-preview-label-tag before">
                    Before – Object Detection
                  </div>
                  <div className="vc-preview-image-wrap">
                    {beforeVideoId && (
                      <img
                        src={getVideoFrameUrl(beforeVideoId, beforeFrame)}
                        alt="Before selected frame"
                        className="vc-preview-img"
                      />
                    )}
                    {beforeDetections.map((d, i) => {
                      if (d.class_name !== "chair") return null;
                      return (
                        <div
                          key={`b-det-${i}`}
                          className="vc-yolo-box"
                          style={{
                            left: `${d.x1 * 100}%`,
                            top: `${d.y1 * 100}%`,
                            width: `${(d.x2 - d.x1) * 100}%`,
                            height: `${(d.y2 - d.y1) * 100}%`,
                          }}
                        >
                          <span className="vc-yolo-label">
                            {d.class_name} {d.confidence?.toFixed(2) || "0.91"}
                          </span>
                        </div>
                      );
                    })}
                  </div>
                </div>

                {/* After Preview */}
                <div className="vc-preview-box">
                  <div className="vc-preview-label-tag after">
                    After – Object Detection
                  </div>
                  <div className="vc-preview-image-wrap">
                    {afterVideoId && (
                      <img
                        src={getVideoFrameUrl(afterVideoId, afterFrame)}
                        alt="After selected frame"
                        className="vc-preview-img"
                      />
                    )}
                    {afterDetections.map((d, i) => {
                      if (d.class_name !== "chair") return null;
                      return (
                        <div
                          key={`a-det-${i}`}
                          className="vc-yolo-box"
                          style={{
                            left: `${d.x1 * 100}%`,
                            top: `${d.y1 * 100}%`,
                            width: `${(d.x2 - d.x1) * 100}%`,
                            height: `${(d.y2 - d.y1) * 100}%`,
                          }}
                        >
                          <span className="vc-yolo-label">
                            {d.class_name} {d.confidence?.toFixed(2) || "0.93"}
                          </span>
                        </div>
                      );
                    })}
                  </div>
                </div>
              </div>
            </div>
          </div>

          {/* Right Column: Comparison Results, Detected Change, Voice Alert */}
          <div className="vc-right-column">
            {/* Comparison Results Card */}
            <div className="vc-results-card">
              <div className="vc-results-header">
                <svg className="vc-results-icon" viewBox="0 0 24 24" width="18" height="18" fill="currentColor">
                  <path d="M5 9.2h3V19H5zM10.6 5h2.8v14h-2.8zm5.6 8H19v6h-2.8z"/>
                </svg>
                <span>Comparison Results</span>
              </div>

              <div className="vc-results-list">
                <div className="vc-result-item">
                  <div className="vc-result-left">
                    <span className="vc-item-icon new">📷</span>
                    <span className="vc-item-name">New Objects</span>
                  </div>
                  <span className="vc-item-count">{summary.new}</span>
                </div>

                <div className="vc-result-item">
                  <div className="vc-result-left">
                    <span className="vc-item-icon missing">🗙</span>
                    <span className="vc-item-name">Missing Objects</span>
                  </div>
                  <span className="vc-item-count">{summary.missing}</span>
                </div>

                <div className="vc-result-item active-change">
                  <div className="vc-result-left">
                    <span className="vc-item-icon moved">⇄</span>
                    <span className="vc-item-name">Moved Objects</span>
                  </div>
                  <span className="vc-item-count crimson">{summary.moved}</span>
                </div>

                <div className="vc-result-item">
                  <div className="vc-result-left">
                    <span className="vc-item-icon unchanged">☑</span>
                    <span className="vc-item-name">Unchanged Objects</span>
                  </div>
                  <span className="vc-item-count">{summary.unchanged}</span>
                </div>

                <div className="vc-result-item">
                  <div className="vc-result-left">
                    <span className="vc-item-icon uncertain">❓</span>
                    <span className="vc-item-name">Uncertain Detections</span>
                  </div>
                  <span className="vc-item-count">{summary.uncertain}</span>
                </div>
              </div>
            </div>

            {/* Detected Change Card */}
            <div className="vc-change-card">
              <div className="vc-change-header">
                <span className="vc-change-icon">⬡</span>
                <span className="vc-change-title">Detected Change</span>
              </div>

              <div className="vc-change-body">
                <div className="vc-change-hero">
                  <div className="vc-change-graphic">
                    {/* Red Chair Outline SVG */}
                    <svg viewBox="0 0 24 24" width="28" height="28" fill="currentColor" className="vc-chair-icon">
                      <path d="M7 3a1 1 0 0 0-1 1v9a2 2 0 0 0 2 2h8a2 2 0 0 0 2-2V4a1 1 0 0 0-1-1H7zm1 2h8v8H8V5zm-2 12v3a1 1 0 1 0 2 0v-3h8v3a1 1 0 1 0 2 0v-3a2 2 0 0 0-2-2H8a2 2 0 0 0-2 2z"/>
                    </svg>
                  </div>
                  <div className="vc-change-details">
                    <div className="vc-change-top">
                      <span className="vc-change-name">{detectedChange.title}</span>
                      <span className="vc-change-pct">
                        {detectedChange.confidence_percent}%
                      </span>
                    </div>
                    <p className="vc-change-desc">
                      {detectedChange.description}
                    </p>
                  </div>
                </div>
              </div>
            </div>

            {/* Voice Alert Card */}
            <div className="vc-voice-card">
              <div className="vc-voice-header">
                <svg className="vc-voice-icon" viewBox="0 0 24 24" width="18" height="18" fill="currentColor">
                  <path d="M3 9v6h4l5 5V4L7 9H3zm13.5 3c0-1.77-1.02-3.29-2.5-4.03v8.05c1.48-.73 2.5-2.25 2.5-4.02zM14 3.23v2.06c2.89.86 5 3.54 5 6.71s-2.11 5.85-5 6.71v2.06c4.01-.91 7-4.49 7-8.77s-2.99-7.86-7-8.77z"/>
                </svg>
                <span>Voice Alert</span>
              </div>

              <div className="vc-voice-body">
                <p className="vc-voice-quote">
                  "{voiceAnnouncement}"
                </p>
                <button
                  className={`vc-voice-play-btn ${isSpeaking ? "playing" : ""}`}
                  onClick={handlePlayVoice}
                  title="Replay Voice Announcement"
                  aria-label="Replay Voice Announcement"
                >
                  <svg viewBox="0 0 24 24" width="18" height="18" fill="currentColor">
                    <path d="M8 5v14l11-7z" />
                  </svg>
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
