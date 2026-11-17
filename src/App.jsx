import { useCallback, useEffect, useRef, useState } from "react";
import "./App.css";
import {
  compareLayouts,
  DEFAULT_CAMERA_ID,
  readJson,
} from "./utils/apiClient.js";
import { captureJpegFromVideo } from "./utils/imageCapture.js";
import {
  isSpeechSynthesisSupported,
  speakText,
  cancelSpeech,
  unlockSpeechSynthesis,
  formatAlertAnnouncement,
  formatComparisonAnnouncement,
} from "./voice/voiceSynthesis.js";
import {
  isSpeechRecognitionSupported,
  createRecognition,
} from "./voice/voiceRecognition.js";
import { formatDate } from "./utils/formatters.js";
import RoomSelector from "./components/rooms/RoomSelector.jsx";
import CameraPanel from "./components/camera/CameraPanel.jsx";
import BaselinePanel from "./components/camera/BaselinePanel.jsx";
import ComparisonModal from "./components/monitoring/ComparisonModal.jsx";
import LiveObjects from "./components/monitoring/LiveObjects.jsx";
import AlertHistory from "./components/alerts/AlertHistory.jsx";
import FindPanel from "./components/objectFinder/FindPanel.jsx";
import SavedLayoutsPanel from "./components/layouts/SavedLayoutsPanel.jsx";

const PRESET_ROOMS = ["Bedroom", "Kitchen", "Living room", "Bathroom", "Other"];
const DEFAULT_ROOM = "Living room";
const OBSERVATION_INTERVAL_MS = 2500;
// AbortController timeout for baseline fetches (ms)
const BASELINE_FETCH_TIMEOUT_MS = 10000;

function App() {
  const videoRef = useRef(null);
  const canvasRef = useRef(null);
  const streamRef = useRef(null);
  const cameraStartGenerationRef = useRef(0);
  const cameraStartInFlightRef = useRef(false);
  const componentMountedRef = useRef(false);
  const speechSupportedRef = useRef(false);
  const lastCameraStatusRef = useRef("");
  const captureInFlightRef = useRef(false);
  const comparisonInFlightRef = useRef(false);
  const comparisonGenerationRef = useRef(0);

  const [roomName, setRoomName] = useState(DEFAULT_ROOM);
  const [customRoomName, setCustomRoomName] = useState("");
  const [isCustomRoom, setIsCustomRoom] = useState(false);
  const [knownRooms, setKnownRooms] = useState([]);
  const [cameraActive, setCameraActive] = useState(false);
  const [cameraStarting, setCameraStarting] = useState(false);
  const [cameraStartCanceled, setCameraStartCanceled] = useState(false);
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
  const [beforeLayout, setBeforeLayout] = useState(null);
  const [afterLayout, setAfterLayout] = useState(null);
  const [activeTab, setActiveTab] = useState("monitor"); // "monitor" | "history" | "find"
  const [backendDown, setBackendDown] = useState(false);
  const [retryCount, setRetryCount] = useState(0);
  const [voiceEnabled, setVoiceEnabled] = useState(true);
  const [voiceUnlocked, setVoiceUnlocked] = useState(false);
  const [lastSpokenAnnouncement, setLastSpokenAnnouncement] = useState("");
  const [cameraViewStatus, setCameraViewStatus] = useState("stable");
  const [liveDetections, setLiveDetections] = useState([]);
  const [liveComparison, setLiveComparison] = useState(null);

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
      if (!voiceEnabled) return;
      if (!speechSupportedRef.current || !isSpeechSynthesisSupported()) {
        recordPlayback(event, "unavailable", "Speech playback is unavailable in this browser.");
        return;
      }
      const formatted = formatAlertAnnouncement(event);
      setLastSpokenAnnouncement(formatted);
      speakText(formatted, {
        rate: 0.92,
        onEnd: () => recordPlayback(event, "spoken"),
        onError: (speechEvent) => {
          const reason = speechEvent.error || "Browser speech playback failed.";
          recordPlayback(event, "failed", reason);
          setMonitorMessage(`Voice alert could not be played: ${reason}`);
        },
      });
    },
    [voiceEnabled, recordPlayback],
  );

  const handleReplayVoice = useCallback(
    (overrideText) => {
      const text =
        overrideText ||
        lastSpokenAnnouncement ||
        (history.length > 0 ? history[0].message : "No recent alerts to announce.");
      if (!text) return;
      unlockSpeechSynthesis();
      speakText(text, { rate: 0.92 });
    },
    [lastSpokenAnnouncement, history],
  );

  const handleToggleVoice = useCallback(() => {
    setVoiceEnabled((prev) => {
      const next = !prev;
      if (!next) {
        cancelSpeech();
      } else {
        unlockSpeechSynthesis();
        speakText("Voice alerts enabled.", { rate: 0.92 });
      }
      return next;
    });
  }, []);

  const handleInitializeVoice = useCallback(() => {
    const success = unlockSpeechSynthesis();
    if (success) {
      setVoiceUnlocked(true);
      speakText("Voice alerts initialized and active.", { rate: 0.92 });
      setNotice("Voice alerts initialized. Chrome audio playback permissions unlocked.");
    }
  }, []);

  const handleTestVoice = useCallback(() => {
    unlockSpeechSynthesis();
    setVoiceUnlocked(true);
    const testMsg = "Voice alert test successful. Speech synthesis is active.";
    setLastSpokenAnnouncement(testMsg);
    speakText(testMsg, { rate: 0.92 });
    setNotice("Voice test played. Speech synthesis is active.");
  }, []);

  const handleRestoreView = useCallback(() => {
    setNotice("Align your camera with the original learned viewpoint. Re-verifying camera stability...");
    setCameraViewStatus("stable");
  }, []);

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
  useEffect(() => {
    componentMountedRef.current = true;
    const video = videoRef.current;
    return () => {
      componentMountedRef.current = false;
      cameraStartGenerationRef.current += 1;
      const stream = streamRef.current;
      streamRef.current = null;
      stream?.getTracks().forEach((track) => track.stop());
      if (video?.srcObject === stream) video.srcObject = null;
      cancelSpeech();
    };
  }, []);

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
            setCameraViewStatus("moved");
            setMonitorMessage("Camera view changed. Alerts are paused until you restore the learned viewpoint or relearn this room.");
            if (voiceEnabled) {
              speakText("Warning! The camera has moved. Room change alerts are paused until you restore the viewpoint.", { rate: 0.92 });
            }
          } else if (result.status === "view_unverified") {
            setCameraViewStatus("unknown");
            setMonitorMessage("Camera view could not be verified. Changes are not being announced to avoid false alerts.");
            if (voiceEnabled) {
              speakText("Camera view cannot be verified due to viewpoint or lighting changes. Monitoring is paused.", { rate: 0.92 });
            }
          } else {
            setCameraViewStatus("stable");
            setMonitorMessage("Monitoring this camera view for confirmed changes. Room is stable.");
          }
        }

        if (result.live_detections) {
          setLiveDetections(result.live_detections);
        } else if (result.latest?.detections) {
          setLiveDetections(result.latest.detections);
        }
        if (result.comparison) {
          setLiveComparison(result.comparison);
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
  }, [baseline, cameraActive, effectiveRoomName, speakAlert, voiceEnabled]);

  async function startCamera() {
    if (cameraStartInFlightRef.current || streamRef.current) return;

    setError("");
    setNotice("");

    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      setError("Your browser does not support webcam access. Use Chrome, Edge, or Firefox over localhost.");
      return;
    }

    cameraStartInFlightRef.current = true;
    const requestGeneration = ++cameraStartGenerationRef.current;
    setCameraStarting(true);
    setCameraStartCanceled(false);
    setMonitorMessage("Requesting camera permission…");
    let stream = null;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: false, video: true });
      if (requestGeneration !== cameraStartGenerationRef.current) {
        stream.getTracks().forEach((track) => track.stop());
        return;
      }

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

      if (requestGeneration !== cameraStartGenerationRef.current) {
        stream.getTracks().forEach((track) => track.stop());
        if (streamRef.current === stream) streamRef.current = null;
        if (video.srcObject === stream) video.srcObject = null;
        return;
      }

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
        if (streamRef.current === stream) streamRef.current = null;
        if (videoRef.current?.srcObject === stream) videoRef.current.srcObject = null;
      }
      if (
        requestGeneration !== cameraStartGenerationRef.current
        || !componentMountedRef.current
      ) return;

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
    } finally {
      cameraStartInFlightRef.current = false;
      if (componentMountedRef.current) {
        setCameraStarting(false);
        setCameraStartCanceled(false);
      }
    }
  }

  function stopCamera() {
    const startupPending = cameraStartInFlightRef.current;
    cameraStartGenerationRef.current += 1;
    if (startupPending) setCameraStartCanceled(true);
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
    if (videoRef.current) videoRef.current.srcObject = null;
    setCameraActive(false);
    setLiveDetections([]);
    setLiveComparison(null);
    setMonitorMessage(
      startupPending
        ? "Camera startup canceled. Waiting for the permission request to finish."
        : "Monitoring is stopped."
    );
  }

  async function captureLayout(replace = false) {
    if (captureInFlightRef.current) return;

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

    captureInFlightRef.current = true;
    try {
      if (replace && !window.confirm(`Replace the saved layout for "${name}"? This cannot be undone.`)) return;

      setBusy(true);
      setError("");
      setNotice("");

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
      invalidateSavedComparisonRequest();
      setComparison(null);
      setShowComparison(false);
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
      captureInFlightRef.current = false;
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


  function invalidateSavedComparisonRequest() {
    comparisonGenerationRef.current += 1;
    comparisonInFlightRef.current = false;
  }

  function resetSavedComparison() {
    invalidateSavedComparisonRequest();
    setBeforeLayout(null);
    setAfterLayout(null);
    setComparison(null);
    setShowComparison(false);
  }

  function handleComparisonLayoutSaved(stage, layout) {
    invalidateSavedComparisonRequest();
    if (stage === "before") {
      setBeforeLayout(layout);
      setAfterLayout(null);
    } else {
      setAfterLayout(layout);
    }
    setComparison(null);
    setShowComparison(false);
  }

  async function handleShowComparison() {
    const name = effectiveRoomName;
    const pairIsInScope =
      beforeLayout
      && afterLayout
      && beforeLayout.room_name.toLowerCase() === name.toLowerCase()
      && afterLayout.room_name.toLowerCase() === name.toLowerCase()
      && beforeLayout.camera_id === DEFAULT_CAMERA_ID
      && afterLayout.camera_id === DEFAULT_CAMERA_ID;
    if (!pairIsInScope || comparisonInFlightRef.current) return;

    comparisonInFlightRef.current = true;
    const requestGeneration = comparisonGenerationRef.current;
    setError("");
    setComparison({ status: "loading", before: beforeLayout, after: afterLayout });
    setShowComparison(true);
    try {
      const result = await compareLayouts({
        roomName: name,
        cameraId: DEFAULT_CAMERA_ID,
        beforeLayoutId: beforeLayout.id,
        afterLayoutId: afterLayout.id,
      });
      if (requestGeneration !== comparisonGenerationRef.current) return;
      if (!["changed", "unchanged", "uncertain"].includes(result.status)) {
        throw new Error("The comparison service returned an unsupported result.");
      }
      setComparison(result);
      const announcement = formatComparisonAnnouncement(result, name);
      setLastSpokenAnnouncement(announcement);
      if (voiceEnabled) {
        if (!isSpeechSynthesisSupported()) {
          setComparison((current) => ({
            ...current,
            speechWarning: "Comparison complete, but speech playback is unavailable in this browser.",
          }));
        } else {
          try {
            speakText(announcement, {
              rate: 0.92,
              onError: (speechEvent) => {
                const reason = speechEvent.error || "Browser speech playback failed.";
                setComparison((current) => current && ({
                  ...current,
                  speechWarning: `Voice alert could not be played: ${reason}. Use Replay Voice to hear it.`,
                }));
              },
            });
          } catch (speechError) {
            setComparison((current) => current && ({
              ...current,
              speechWarning: `Voice alert could not be played: ${speechError.message}`,
            }));
          }
        }
      }
    } catch (comparisonError) {
      if (requestGeneration !== comparisonGenerationRef.current) return;
      setComparison({
        status: "error",
        error: comparisonError.message,
        before: beforeLayout,
        after: afterLayout,
      });
    } finally {
      if (requestGeneration === comparisonGenerationRef.current) {
        comparisonInFlightRef.current = false;
      }
    }
  }

  function handleLayoutSaved(layout) {
    invalidateSavedComparisonRequest();
    setBaseline(layout);
    setLatest(null);
    setComparison(null);
    setShowComparison(false);
    setMonitorMessage(
      cameraActive
        ? "New layout saved and active. Monitoring remains on while the camera view is revalidated."
        : "New layout saved and active. Monitoring remains stopped until you start it.",
    );
    void loadKnownRooms();
  }

  function handleLayoutActivated(layout) {
    invalidateSavedComparisonRequest();
    setBaseline(layout);
    setLatest(null);
    setComparison(null);
    setShowComparison(false);
    setMonitorMessage(
      cameraActive
        ? "Saved layout restored. Monitoring remains on while the camera view is revalidated."
        : "Saved layout restored. Monitoring remains stopped; start it when you are ready.",
    );
  }

  const hasCurrentRoomBaseline =
    baseline && baseline.room_name.toLowerCase() === effectiveRoomName.toLowerCase();
  const canCompareSavedLayouts =
    beforeLayout
    && afterLayout
    && beforeLayout.room_name.toLowerCase() === effectiveRoomName.toLowerCase()
    && afterLayout.room_name.toLowerCase() === effectiveRoomName.toLowerCase()
    && beforeLayout.camera_id === DEFAULT_CAMERA_ID
    && afterLayout.camera_id === DEFAULT_CAMERA_ID;

  const knownObjectNames = new Set((baseline?.detections || []).map((item) => item.class_name));

  const monitoringState = !cameraActive
    ? "idle"
    : cameraViewStatus === "moved"
    ? "moved"
    : cameraViewStatus === "unknown"
    ? "paused"
    : "active";

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
          if (cameraActive || cameraStartInFlightRef.current) stopCamera();
          resetSavedComparison();
          setIsCustomRoom(false);
          setRoomName(room);
          setError("");
          setFindResult("");
          setBaselineLoading(true);
        }}
        onCustomToggle={() => {
          if (cameraActive || cameraStartInFlightRef.current) stopCamera();
          resetSavedComparison();
          setIsCustomRoom(true);
          setError("");
          setFindResult("");
          setBaselineLoading(true);
        }}
        onCustomNameChange={(name) => {
          if (cameraStartInFlightRef.current) stopCamera();
          resetSavedComparison();
          setCustomRoomName(name);
          setError("");
          setFindResult("");
          setBaselineLoading(true);
        }}
        onKnownRoomSelect={(r) => {
          if (cameraActive || cameraStartInFlightRef.current) stopCamera();
          resetSavedComparison();
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
          cameraStarting={cameraStarting}
          cameraStartCanceled={cameraStartCanceled}
          baselineDetectionCount={baseline?.detections?.length ?? 0}
          baselineLoading={baselineLoading}
          busy={busy}
          hasCurrentRoomBaseline={hasCurrentRoomBaseline}
          canCompareSavedLayouts={Boolean(canCompareSavedLayouts)}
          monitoringState={monitoringState}
          monitorMessage={monitorMessage}
          voiceEnabled={voiceEnabled}
          voiceUnlocked={voiceUnlocked}
          liveDetections={liveDetections}
          knownObjectNames={knownObjectNames}
          lastScanTime={latest?.captured_at ? formatDate(latest.captured_at) : ""}
          videoRef={videoRef}
          canvasRef={canvasRef}
          onStart={startCamera}
          onStop={stopCamera}
          onCapture={captureLayout}
          onShowComparison={() => void handleShowComparison()}
          onRestoreView={handleRestoreView}
          onInitializeVoice={handleInitializeVoice}
          onReplayVoice={handleReplayVoice}
          onTestVoice={handleTestVoice}
          onToggleVoice={handleToggleVoice}
        />
        <BaselinePanel
          baseline={baseline}
          baselineLoading={baselineLoading}
          hasCurrentRoomBaseline={hasCurrentRoomBaseline}
          effectiveRoomName={effectiveRoomName}
        />
      </section>

      <SavedLayoutsPanel
        key={`${effectiveRoomName}\u0000${DEFAULT_CAMERA_ID}`}
        roomName={effectiveRoomName}
        cameraId={DEFAULT_CAMERA_ID}
        cameraActive={cameraActive}
        videoRef={videoRef}
        beforeLayout={beforeLayout}
        afterLayout={afterLayout}
        onComparisonLayoutSaved={handleComparisonLayoutSaved}
        onStartNewComparison={resetSavedComparison}
        onLayoutSaved={handleLayoutSaved}
        onLayoutActivated={handleLayoutActivated}
      />

      {/* ── BEFORE / AFTER COMPARISON MODAL ── */}
      {showComparison && comparison && (
        <ComparisonModal
          comparison={comparison}
          effectiveRoomName={effectiveRoomName}
          voiceEnabled={voiceEnabled}
          onReplayVoice={handleReplayVoice}
          onTestVoice={handleTestVoice}
          onToggleVoice={handleToggleVoice}
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
            baseline={baseline}
            liveComparison={liveComparison}
            knownObjectNames={knownObjectNames}
            cameraActive={cameraActive}
            monitoringState={monitoringState}
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
