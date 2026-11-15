import { useCallback, useEffect, useRef, useState } from "react";
import "./App.css";
import { readJson } from "./utils/apiClient.js";
import { captureJpegFromVideo } from "./utils/imageCapture.js";
import {
  isSpeechSynthesisSupported,
  speakText,
  cancelSpeech,
} from "./voice/voiceSynthesis.js";
import {
  isSpeechRecognitionSupported,
  createRecognition,
} from "./voice/voiceRecognition.js";
import RoomSelector from "./components/rooms/RoomSelector.jsx";
import CameraPanel from "./components/camera/CameraPanel.jsx";
import BaselinePanel from "./components/camera/BaselinePanel.jsx";
import ComparisonModal from "./components/monitoring/ComparisonModal.jsx";
import LiveObjects from "./components/monitoring/LiveObjects.jsx";
import AlertHistory from "./components/alerts/AlertHistory.jsx";
import FindPanel from "./components/objectFinder/FindPanel.jsx";

const PRESET_ROOMS = ["Bedroom", "Kitchen", "Living room", "Bathroom", "Other"];
const DEFAULT_ROOM = "Living room";
const OBSERVATION_INTERVAL_MS = 2500;
// AbortController timeout for baseline fetches (ms)
const BASELINE_FETCH_TIMEOUT_MS = 10000;

function App() {
  const videoRef = useRef(null);
  const canvasRef = useRef(null);
  const streamRef = useRef(null);
  const speechSupportedRef = useRef(false);
  const lastCameraStatusRef = useRef("");

  const [roomName, setRoomName] = useState(DEFAULT_ROOM);
  const [customRoomName, setCustomRoomName] = useState("");
  const [isCustomRoom, setIsCustomRoom] = useState(false);
  const [knownRooms, setKnownRooms] = useState([]);
  const [cameraActive, setCameraActive] = useState(false);
  const [busy, setBusy] = useState(false);

  const [baseline, setBaseline] = useState(null);
  const [latest, setLatest] = useState(null);
  const [history, setHistory] = useState([]);
  const [findQuery, setFindQuery] = useState("");
  const [findResult, setFindResult] = useState("");
  const [baselineLoading, setBaselineLoading] = useState(true);
  const [monitorMessage, setMonitorMessage] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [showComparison, setShowComparison] = useState(false);
  const [comparison, setComparison] = useState(null);
  const [activeTab, setActiveTab] = useState("monitor"); // "monitor" | "history" | "find"
  const [backendDown, setBackendDown] = useState(false);
  const [retryCount, setRetryCount] = useState(0);

  const effectiveRoomName = isCustomRoom ? customRoomName.trim() : roomName;

  // Load known rooms from API
  const loadKnownRooms = useCallback(async () => {
    try {
      const response = await fetch("/api/rooms");
      const data = await readJson(response);
      setKnownRooms(data.rooms || []);
    } catch {
      // Non-fatal: rooms list is for convenience
    }
  }, []);

  const loadHistory = useCallback(async (name) => {
    const response = await fetch(`/api/alerts?room_name=${encodeURIComponent(name)}`);
    const result = await readJson(response);
    setHistory(result.history);
  }, []);

  const loadComparison = useCallback(async (name) => {
    const response = await fetch(`/api/comparison?room_name=${encodeURIComponent(name)}`);
    const result = await readJson(response);
    setComparison(result);
  }, []);

  const recordPlayback = useCallback(async (event, status, playbackError) => {
    try {
      await readJson(
        await fetch(`/api/alerts/${event.id}/playback`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ status, error: playbackError }),
        }),
      );
      setHistory((current) =>
        current.map((item) =>
          item.id === event.id
            ? { ...item, speech_status: status, speech_error: playbackError || null }
            : item,
        ),
      );
    } catch (playbackRecordError) {
      setMonitorMessage(`Could not update alert playback history: ${playbackRecordError.message}`);
    }
  }, []);

  const speakAlert = useCallback(
    (event) => {
      if (!speechSupportedRef.current || !isSpeechSynthesisSupported()) {
        recordPlayback(event, "unavailable", "Speech playback is unavailable in this browser.");
        return;
      }
      speakText(event.message, {
        rate: 0.92,
        onEnd: () => recordPlayback(event, "spoken"),
        onError: (speechEvent) => {
          const reason = speechEvent.error || "Browser speech playback failed.";
          recordPlayback(event, "failed", reason);
          setMonitorMessage(`Voice alert could not be played: ${reason}`);
        },
      });
    },
    [recordPlayback],
  );

  // Load baseline whenever the effective room name changes or a retry is triggered.
  // AbortController cancels in-flight requests when the room changes so stale
  // responses from a slow previous fetch never overwrite the new room's data.
  useEffect(() => {
    const name = effectiveRoomName || DEFAULT_ROOM;
    if (!name) return;

    const controller = new AbortController();
    const timeoutId = window.setTimeout(() => controller.abort(), BASELINE_FETCH_TIMEOUT_MS);
    const q = encodeURIComponent(name);

    fetch(`/api/baseline?room_name=${q}`, { signal: controller.signal })
      .then((r) => {
        if (!r.ok) throw new Error(`Server error ${r.status}`);
        return r.json();
      })
      .then(({ baseline: savedBaseline }) =>
        fetch(`/api/latest?room_name=${q}`, { signal: controller.signal })
          .then((r) => {
            if (!r.ok) throw new Error(`Server error ${r.status}`);
            return r.json();
          })
          .then((savedLatest) => {
            window.clearTimeout(timeoutId);
            setBaseline(savedBaseline);
            setLatest(savedLatest.latest);
            setHistory(savedLatest.history);
            setBackendDown(false);
            setBaselineLoading(false);
          }),
      )
      .catch((err) => {
        window.clearTimeout(timeoutId);
        if (err.name === "AbortError") return;
        setBaseline(null);
        setLatest(null);
        setHistory([]);
        setBaselineLoading(false);
        if (err.message === "Failed to fetch" || err.message.includes("NetworkError")) {
          setBackendDown(true);
        } else {
          setError(`Could not load room data: ${err.message}. Start Flask: python -m ai.server`);
        }
      });

    return () => {
      controller.abort();
      window.clearTimeout(timeoutId);
    };
  }, [effectiveRoomName, retryCount]);

  // Load rooms list on mount — inlined so the linter can see setState is
  // only called inside an async callback, not synchronously in the effect body.
  useEffect(() => {
    fetch("/api/rooms")
      .then((res) => res.json())
      .then((data) => { setKnownRooms(data.rooms || []); })
      .catch(() => { /* non-fatal */ });
  }, []);

  // Cleanup on unmount
  useEffect(
    () => () => {
      streamRef.current?.getTracks().forEach((track) => track.stop());
      cancelSpeech();
    },
    [],
  );

  // Monitoring loop
  useEffect(() => {
    if (!cameraActive || !baseline || !baseline.detections.length || !videoRef.current || !canvasRef.current) {
      return undefined;
    }

    let requestInFlight = false;
    const controller = new AbortController();

    async function scanFrame() {
      const video = videoRef.current;
      if (requestInFlight || !video || video.readyState < HTMLMediaElement.HAVE_CURRENT_DATA || video.videoWidth === 0) return;

      requestInFlight = true;
      try {
        // Use guaranteed-JPEG helper (async) to avoid PNG fallback in some browsers
        const imageDataUrl = await captureJpegFromVideo(video, 0.72);

        const result = await readJson(
          await fetch("/api/observe", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              room_name: effectiveRoomName,
              image: imageDataUrl,
            }),
            signal: controller.signal,
          }),
        );

        if (controller.signal.aborted) return;

        if (result.status !== lastCameraStatusRef.current) {
          lastCameraStatusRef.current = result.status;
          if (result.status === "camera_moved") {
            setMonitorMessage("Camera view changed. Alerts are paused until you restore the learned viewpoint or relearn this room.");
          } else if (result.status === "view_unverified") {
            setMonitorMessage("Camera view could not be verified. Changes are not being announced to avoid false alerts.");
          } else {
            setMonitorMessage("Monitoring this camera view for confirmed changes. Alerts require repeated detections.");
          }
        }

        if (result.latest) setLatest(result.latest);
        setHistory(result.history);
        for (const event of result.alerts) speakAlert(event);
      } catch (scanError) {
        if (scanError.name !== "AbortError") {
          setMonitorMessage(`Monitoring paused after an error: ${scanError.message}`);
        }
      } finally {
        requestInFlight = false;
      }
    }

    scanFrame();
    const timer = window.setInterval(scanFrame, OBSERVATION_INTERVAL_MS);
    return () => {
      window.clearInterval(timer);
      controller.abort();
    };
  }, [baseline, cameraActive, effectiveRoomName, speakAlert]);

  async function startCamera() {
    setError("");
    setNotice("");

    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      setError("Your browser does not support webcam access. Use Chrome, Edge, or Firefox over localhost.");
      return;
    }

    setMonitorMessage("Requesting camera permission…");
    let stream = null;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: false, video: true });
      streamRef.current = stream;
      const video = videoRef.current;
      video.srcObject = stream;

      // Wait for the video to be truly ready to play.
      // Use a one-shot settler so timeout, onloadedmetadata, and onerror
      // cannot resolve or reject the same Promise more than once.
      await new Promise((resolve, reject) => {
        let settled = false;
        const settle = (fn, value) => {
          if (settled) return;
          settled = true;
          clearTimeout(timer);
          video.onloadedmetadata = null;
          video.onerror = null;
          fn(value);
        };

        // 6-second hard timeout — longer than typical camera init time
        const timer = setTimeout(() => {
          // Timeout is not a failure if the video is already playing
          if (video.readyState >= HTMLMediaElement.HAVE_CURRENT_DATA) {
            settle(resolve, undefined);
          } else {
            settle(reject, new Error("Camera timed out while waiting to start. Try again."));
          }
        }, 6000);

        video.onloadedmetadata = () => {
          video.play()
            .then(() => settle(resolve, undefined))
            .catch((playErr) => settle(reject, playErr));
        };

        video.onerror = (e) => {
          settle(reject, e.error || new Error("Video element error during camera startup."));
        };

        // If metadata already loaded (srcObject was set on a reused element)
        if (video.readyState >= HTMLMediaElement.HAVE_METADATA) {
          video.play()
            .then(() => settle(resolve, undefined))
            .catch((playErr) => settle(reject, playErr));
        }
      });

      speechSupportedRef.current = isSpeechSynthesisSupported();
      lastCameraStatusRef.current = "";
      setMonitorMessage(
        hasCurrentRoomBaseline && baseline && baseline.detections.length
          ? "Starting room monitoring..."
          : "Webcam is live. Point it at the room and click 📷 Capture Original Layout."
      );
      setCameraActive(true);
    } catch (cameraError) {
      // Stop any tracks that were acquired before the failure
      if (stream) {
        stream.getTracks().forEach((t) => t.stop());
        streamRef.current = null;
        if (videoRef.current) videoRef.current.srcObject = null;
      }
      setMonitorMessage("");
      const ename = cameraError.name;
      if (ename === "NotAllowedError" || ename === "PermissionDeniedError") {
        setError("Camera access was denied. Click the 🔒 lock icon in the address bar → Allow Camera, then try again.");
      } else if (ename === "NotFoundError" || ename === "DevicesNotFoundError") {
        setError("No camera found. Connect a webcam and try again.");
      } else if (ename === "NotReadableError" || ename === "TrackStartError") {
        setError("Camera is in use by another app (Teams, Zoom, etc). Close it and try again.");
      } else {
        setError(`Could not start the webcam: ${cameraError.message}`);
      }
    }
  }

  function stopCamera() {
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
    if (videoRef.current) videoRef.current.srcObject = null;
    setCameraActive(false);
    setMonitorMessage("Monitoring is stopped.");
  }

  async function captureLayout(replace = false) {
    const name = effectiveRoomName;
    const video = videoRef.current;

    if (!name) {
      setError("Select or enter a room name before capturing.");
      return;
    }
    if (!video || video.readyState < HTMLMediaElement.HAVE_CURRENT_DATA || video.videoWidth === 0) {
      setError("Webcam is not ready yet. Wait for the live preview to appear, then capture.");
      return;
    }

    if (replace && !window.confirm(`Replace the saved layout for "${name}"? This cannot be undone.`)) return;

    setBusy(true);
    setError("");
    setNotice("");
    try {
      // Capture a guaranteed JPEG frame from the live video feed (async)
      let imageDataUrl;
      try {
        imageDataUrl = await captureJpegFromVideo(video, 0.82);
      } catch (captureError) {
        throw new Error(`Could not capture webcam frame: ${captureError.message}`, { cause: captureError });
      }

      setNotice("Sending image to server for YOLO detection…");

      const response = await fetch("/api/baseline", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ room_name: name, image: imageDataUrl, replace }),
      });

      const result = await readJson(response);
      setBaseline(result.baseline);
      setLatest(null);
      setComparison(null);
      setMonitorMessage("Original layout saved. Start monitoring to detect changes.");
      setNotice(
        result.baseline.detections.length
          ? `✓ Saved ${result.baseline.detections.length} object${result.baseline.detections.length === 1 ? "" : "s"} in the ${name} layout.`
          : `✓ Layout saved for ${name}. No supported objects were detected — try reframing the room.`
      );
      await loadKnownRooms();
      await loadHistory(name).catch((historyError) => {
        // Non-fatal — layout is saved, history refresh failed
        console.warn("History refresh failed after capture:", historyError.message);
      });
    } catch (saveError) {
      setError(`Could not save layout: ${saveError.message}`);
    } finally {
      setBusy(false);
    }
  }

  async function repeatAlertReport() {
    if (!history.length) {
      setNotice("There are no change alerts to repeat.");
      return;
    }
    if (!isSpeechSynthesisSupported()) {
      setError("Speech playback is unavailable in this browser.");
      return;
    }
    const report = history.slice(0, 5).map((event) => event.message).join(" ");
    cancelSpeech();
    speakText(report);
  }

  async function findObject(query = findQuery) {
    const search = query.trim();
    if (!search) {
      setError("Enter or say the name of an object to find.");
      return;
    }
    setError("");
    setFindResult("");
    try {
      const response = await fetch(
        `/api/find?room_name=${encodeURIComponent(effectiveRoomName)}&object_name=${encodeURIComponent(search)}`
      );
      const result = await readJson(response);
      setFindResult(result.message);
      speakText(result.message, {
        onError: (speechEvent) => {
          const reason = speechEvent.error || "Browser speech playback failed.";
          setMonitorMessage(`Object-finding voice response could not be played: ${reason}`);
        },
      });
    } catch (findError) {
      setError(findError.message);
    }
  }

  function startVoiceSearch() {
    if (!isSpeechRecognitionSupported()) {
      setError("Voice recognition is unavailable in this browser. Enter an object name instead.");
      return;
    }
    setError("");
    const recognition = createRecognition("en-US");
    recognition.onresult = (event) => {
      const spokenQuery = event.results[0][0].transcript;
      setFindQuery(spokenQuery);
      void findObject(spokenQuery);
    };
    recognition.onerror = (event) => {
      setError(`Voice search failed: ${event.error}. Enter the object name instead.`);
    };
    try {
      recognition.start();
    } catch (recognitionError) {
      setError(`Could not start voice search: ${recognitionError.message}`);
    }
  }


  async function handleShowComparison() {
    const name = effectiveRoomName;
    if (!name) return;
    await loadComparison(name);
    setShowComparison(true);
  }

  const hasCurrentRoomBaseline =
    baseline && baseline.room_name.toLowerCase() === effectiveRoomName.toLowerCase();

  const knownObjectNames = new Set((baseline?.detections || []).map((item) => item.class_name));

  return (
    <main className="app-shell" role="main">
      {/* ── HEADER ── */}
      <header className="page-header" role="banner">
        <p className="eyebrow" aria-label="Application category">AI INDOOR ROOM ASSISTANT</p>
        <h1>Room Change Detection</h1>
        <p className="intro">
          Helps blind users detect room changes using camera AI and automatic voice alerts.
        </p>
      </header>

      {/* ── BACKEND UNAVAILABLE BANNER ── */}
      {backendDown && (
        <div className="backend-error" role="alert" aria-live="assertive">
          <p>
            <strong>Backend not running.</strong> Start Flask in a terminal:
          </p>
          <code>python -m ai.server</code>
          <button
            className="button button-secondary"
            onClick={() => setRetryCount((n) => n + 1)}
            aria-label="Retry connecting to backend"
          >
            🔄 Retry
          </button>
        </div>
      )}

      {/* ── ROOM SELECTOR ── */}
      <RoomSelector
        presetRooms={PRESET_ROOMS}
        roomName={roomName}
        isCustomRoom={isCustomRoom}
        customRoomName={customRoomName}
        knownRooms={knownRooms}
        onPresetSelect={(room) => {
          if (roomName === room && !isCustomRoom) return;
          if (cameraActive) stopCamera();
          setIsCustomRoom(false);
          setRoomName(room);
          setError("");
          setFindResult("");
          setBaselineLoading(true);
        }}
        onCustomToggle={() => {
          if (cameraActive) stopCamera();
          setIsCustomRoom(true);
          setError("");
          setFindResult("");
          setBaselineLoading(true);
        }}
        onCustomNameChange={(name) => {
          setCustomRoomName(name);
          setError("");
          setFindResult("");
          setBaselineLoading(true);
        }}
        onKnownRoomSelect={(r) => {
          if (cameraActive) stopCamera();
          setIsCustomRoom(false);
          const match = PRESET_ROOMS.find(
            (p) => p.toLowerCase() === r.room_name.toLowerCase()
          );
          if (match) {
            setRoomName(match);
          } else {
            setIsCustomRoom(true);
            setCustomRoomName(r.room_name);
          }
          setError("");
          setFindResult("");
          setBaselineLoading(true);
        }}
      />

      {/* ── CAMERA + LAYOUT CAPTURE ── */}
      <section className="learning-grid" aria-label="Room layout and camera">
        <CameraPanel
          effectiveRoomName={effectiveRoomName}
          cameraActive={cameraActive}
          baselineDetectionCount={baseline?.detections?.length ?? 0}
          baselineLoading={baselineLoading}
          busy={busy}
          hasCurrentRoomBaseline={hasCurrentRoomBaseline}
          hasLatest={!!latest}
          videoRef={videoRef}
          canvasRef={canvasRef}
          onStart={startCamera}
          onStop={stopCamera}
          onCapture={captureLayout}
          onShowComparison={handleShowComparison}
        />
        <BaselinePanel
          baseline={baseline}
          baselineLoading={baselineLoading}
          hasCurrentRoomBaseline={hasCurrentRoomBaseline}
          effectiveRoomName={effectiveRoomName}
        />
      </section>

      {/* ── BEFORE / AFTER COMPARISON MODAL ── */}
      {showComparison && comparison && (
        <ComparisonModal
          comparison={comparison}
          effectiveRoomName={effectiveRoomName}
          onClose={() => setShowComparison(false)}
        />
      )}

      {/* ── MONITORING TABS ── */}
      {hasCurrentRoomBaseline && (
        <section className="monitor-section" aria-label="Monitoring controls">
          {monitorMessage && (
            <div className="monitor-status-bar" role="status" aria-live="polite">
              <span aria-hidden="true">{cameraActive ? "🟢" : "⚪"}</span> {monitorMessage}
            </div>
          )}

          <div className="tab-bar" role="tablist" aria-label="Monitoring sections">
            {[
              { id: "monitor", label: "📡 Live Objects" },
              { id: "history", label: "📋 Alert History" },
              { id: "find", label: "🔎 Find Object" },
            ].map((tab) => (
              <button
                key={tab.id}
                role="tab"
                className={`tab-button ${activeTab === tab.id ? "tab-active" : ""}`}
                aria-selected={activeTab === tab.id}
                onClick={() => setActiveTab(tab.id)}
                aria-controls={`tab-panel-${tab.id}`}
              >
                {tab.label}
                {tab.id === "history" && history.length > 0 && (
                  <span className="tab-badge" aria-label={`${history.length} alerts`}>{history.length}</span>
                )}
              </button>
            ))}
          </div>

          {/* ── LIVE OBJECTS TAB ── */}
          <LiveObjects
            isActive={activeTab === "monitor"}
            latest={latest}
            knownObjectNames={knownObjectNames}
            cameraActive={cameraActive}
          />

          {/* ── HISTORY TAB ── */}
          <AlertHistory
            isActive={activeTab === "history"}
            history={history}
            onRepeat={repeatAlertReport}
          />

          {/* ── FIND OBJECT TAB ── */}
          <FindPanel
            isActive={activeTab === "find"}
            findQuery={findQuery}
            setFindQuery={setFindQuery}
            findResult={findResult}
            onFind={() => { void findObject(); }}
            onVoiceSearch={startVoiceSearch}
          />
        </section>
      )}

      {/* ── FEEDBACK ── */}
      {notice && (
        <p className="feedback feedback-success" role="status" aria-live="polite">{notice}</p>
      )}
      {error && (
        <p className="feedback feedback-error" role="alert" aria-live="assertive">{error}</p>
      )}

      <footer className="scope-note" role="contentinfo">
        <p>
          A single fixed webcam monitors only its visible field of view. Camera movement pauses alerts.
          Image zones are approximate; webcam images cannot provide reliable distance or guarantee safe navigation.
        </p>
      </footer>
    </main>
  );
}

export default App;
