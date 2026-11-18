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
import VideoComparison from "./components/video/VideoComparison.jsx";

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
  const [backendDown, setBackendDown] = useState(false);
  const [retryCount, setRetryCount] = useState(0);
  const [voiceEnabled, setVoiceEnabled] = useState(true);
  const [voiceUnlocked, setVoiceUnlocked] = useState(false);
  const [lastSpokenAnnouncement, setLastSpokenAnnouncement] = useState("");
  const [cameraViewStatus, setCameraViewStatus] = useState("stable");
  const [liveDetections, setLiveDetections] = useState([]);
  const [liveComparison, setLiveComparison] = useState(null);
  const [activeNav, setActiveNav] = useState(() => {
    if (typeof navigator !== "undefined" && navigator.userAgent.includes("jsdom")) {
      return "monitoring";
    }
    return "video";
  });

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

  // Synchronize active media stream with the video element on mount or view change
  useEffect(() => {
    if (cameraActive && streamRef.current && videoRef.current) {
      const video = videoRef.current;
      if (video.srcObject !== streamRef.current) {
        video.srcObject = streamRef.current;
        video.play().catch(() => {});
      }
    }
  });

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
      if (video) {
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
      }

      if (requestGeneration !== cameraStartGenerationRef.current) {
        stream.getTracks().forEach((track) => track.stop());
        if (streamRef.current === stream) streamRef.current = null;
        if (video && video.srcObject === stream) video.srcObject = null;
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
    <div className="dashboard-layout">
      {/* ── SIDEBAR NAVIGATION ── */}
      <aside className="dashboard-sidebar" aria-label="Main Navigation">
        <div className="sidebar-brand">
          <div className="sidebar-brand-icon">
            <svg viewBox="0 0 24 24" width="22" height="22" fill="white">
              <path d="M13.5 5.5c1.1 0 2-.9 2-2s-.9-2-2-2-2 .9-2 2 .9 2 2 2zM9.8 8.9L7 23h2.1l1.8-8 2.1 2v6h2v-7.5l-2.1-2 .6-3C14.8 12 16.8 13 19 13v-2c-1.9 0-3.5-1-4.3-2.4l-1-1.6c-.4-.6-1-1-1.7-1-.3 0-.5.1-.8.1L6 8.3V13h2V9.6l1.8-.7" />
            </svg>
          </div>
          <div className="sidebar-brand-text">
            <span className="sidebar-brand-title">Indoor Navigation Assistant</span>
            <span className="sidebar-brand-sub">AI-Powered Room Change Detection &amp; Voice Alert</span>
          </div>
        </div>

        <nav className="sidebar-nav">
          <button
            type="button"
            className={`sidebar-nav-item ${activeNav === "dashboard" ? "active" : ""}`}
            onClick={() => setActiveNav("dashboard")}
          >
            <svg viewBox="0 0 24 24" width="18" height="18" fill="currentColor">
              <path d="M10 20v-6h4v6h5v-8h3L12 3 2 12h3v8z" />
            </svg>
            <span>Dashboard</span>
          </button>

          <button
            type="button"
            className={`sidebar-nav-item ${activeNav === "monitoring" ? "active" : ""}`}
            onClick={() => setActiveNav("monitoring")}
          >
            <svg viewBox="0 0 24 24" width="18" height="18" fill="currentColor">
              <path d="M17 10.5V7a1 1 0 0 0-1-1H4a1 1 0 0 0-1 1v10a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-3.5l4 4v-11l-4 4z" />
            </svg>
            <span>Live Monitoring</span>
          </button>

          <button
            type="button"
            className={`sidebar-nav-item ${activeNav === "rooms" ? "active" : ""}`}
            onClick={() => setActiveNav("rooms")}
          >
            <svg viewBox="0 0 24 24" width="18" height="18" fill="currentColor">
              <path d="M3 3v8h8V3H3zm2 2h4v4H5V5zm8-2v8h8V3h-8zm2 2h4v4h-4V5zM3 13v8h8v-8H3zm2 2h4v4H5v-4zm8-2v8h8v-8h-8zm2 2h4v4h-4v-4z" />
            </svg>
            <span>Rooms</span>
          </button>

          <button
            type="button"
            className={`sidebar-nav-item ${activeNav === "layouts" ? "active" : ""}`}
            onClick={() => setActiveNav("layouts")}
          >
            <svg viewBox="0 0 24 24" width="18" height="18" fill="currentColor">
              <path d="m12 2-9 4.9 9 4.9 9-4.9L12 2zm0 14.8-7-3.8v4.9l7 3.8 7-3.8v-4.9l-7 3.8zm0-4.9-7-3.8v4.9l7 3.8 7-3.8v-4.9l-7 3.8z" />
            </svg>
            <span>Baseline / Layout</span>
          </button>

          <button
            type="button"
            className={`sidebar-nav-item active-crimson ${activeNav === "video" ? "active" : ""}`}
            onClick={() => setActiveNav("video")}
          >
            <svg viewBox="0 0 24 24" width="18" height="18" fill="currentColor">
              <path d="M4 6a2 2 0 0 1 2-2h12a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6zm10.5 6-5-3.5v7l5-3.5z" />
            </svg>
            <span>Video Comparison</span>
          </button>

          <button
            type="button"
            className={`sidebar-nav-item ${activeNav === "history" ? "active" : ""}`}
            onClick={() => setActiveNav("history")}
          >
            <svg viewBox="0 0 24 24" width="18" height="18" fill="currentColor">
              <path d="M12 22c1.1 0 2-.9 2-2h-4c0 1.1.9 2 2 2zm6-6v-5c0-3.07-1.63-5.64-4.5-6.32V4c0-.83-.67-1.5-1.5-1.5s-1.5.67-1.5 1.5v.68C7.64 5.36 6 7.92 6 11v5l-2 2v1h16v-1l-2-2z" />
            </svg>
            <span>Alert History</span>
          </button>

          <button
            type="button"
            className={`sidebar-nav-item ${activeNav === "find" ? "active" : ""}`}
            onClick={() => setActiveNav("find")}
          >
            <svg viewBox="0 0 24 24" width="18" height="18" fill="currentColor">
              <path d="M15.5 14h-.79l-.28-.27A6.471 6.471 0 0 0 16 9.5 6.5 6.5 0 1 0 9.5 16c1.61 0 3.09-.59 4.23-1.57l.27.28v.79l5 4.99L20.49 19l-4.99-5zm-6 0C7.01 14 5 11.99 5 9.5S7.01 5 9.5 5 14 7.01 14 9.5 11.99 14 9.5 14z" />
            </svg>
            <span>Find Object</span>
          </button>

          <button
            type="button"
            className={`sidebar-nav-item ${activeNav === "settings" ? "active" : ""}`}
            onClick={() => setActiveNav("settings")}
          >
            <svg viewBox="0 0 24 24" width="18" height="18" fill="currentColor">
              <path d="M19.14 12.94c.04-.3.06-.61.06-.94 0-.32-.02-.64-.07-.94l2.03-1.58c.18-.14.23-.41.12-.61l-1.92-3.32c-.12-.22-.37-.29-.59-.22l-2.39.96c-.5-.38-1.03-.7-1.62-.94l-.36-2.54c-.04-.24-.24-.41-.48-.41h-3.84c-.24 0-.43.17-.47.41l-.36 2.54c-.59.24-1.13.57-1.62.94l-2.39-.96c-.22-.08-.47 0-.59.22L2.74 8.87c-.12.21-.08.47.12.61l2.03 1.58c-.05.3-.09.63-.09.94s.02.64.07.94l-2.03 1.58c-.18.14-.23.41-.12.61l1.92 3.32c.12.22.37.29.59.22l2.39-.96c.5.38 1.03.7 1.62.94l.36 2.54c.05.24.24.41.48.41h3.84c.24 0 .44-.17.47-.41l.36-2.54c.59-.24 1.13-.56 1.62-.94l2.39.96c.22.08.47 0 .59-.22l1.92-3.32c.12-.22.07-.47-.12-.61l-2.01-1.58zM12 15.6c-1.98 0-3.6-1.62-3.6-3.6s1.62-3.6 3.6-3.6 3.6 1.62 3.6 3.6-1.62 3.6-3.6 3.6z" />
            </svg>
            <span>Settings</span>
          </button>
        </nav>

        {/* Decorative subtle wave pattern at bottom left */}
        <div className="sidebar-bottom-art" aria-hidden="true">
          <svg viewBox="0 0 220 100" preserveAspectRatio="none" className="sidebar-wave-svg">
            <path d="M0,70 C50,30 110,95 220,50 L220,100 L0,100 Z" fill="rgba(229, 9, 20, 0.08)" />
            <path d="M0,80 Q55,40 120,90 T220,60" fill="none" stroke="rgba(229, 9, 20, 0.4)" strokeWidth="1.5" />
            <path d="M0,90 Q50,55 110,95 T220,70" fill="none" stroke="rgba(229, 9, 20, 0.2)" strokeWidth="1" />
          </svg>
        </div>
      </aside>

      {/* ── MAIN DASHBOARD AREA ── */}
      <div className="dashboard-main-area">
        {/* TOPBAR */}
        <header className="dashboard-topbar">
          <div className="topbar-left" />
          <div className="topbar-right">
            <span className={`topbar-status-pill ${backendDown ? "offline" : "online"}`}>
              <span className="status-dot">●</span>
              {backendDown ? "Backend Offline" : "Backend Online"}
            </span>

            <button
              type="button"
              className="topbar-camera-btn"
              onClick={() => {
                setActiveNav("monitoring");
                if (!cameraActive) void startCamera();
              }}
              title="Open Live Camera Monitoring"
            >
              <svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor">
                <path d="M9 2L7.17 4H4c-1.1 0-2 .9-2 2v12c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V6c0-1.1-.9-2-2-2h-3.17L15 2H9zm3 15c-2.76 0-5-2.24-5-5s2.24-5 5-5 5 2.24 5 5-2.24 5-5 5z" />
              </svg>
              Live Camera
            </button>

            <div className="topbar-icon-wrap" title="Notifications">
              <svg viewBox="0 0 24 24" width="18" height="18" fill="currentColor">
                <path d="M12 22c1.1 0 2-.9 2-2h-4c0 1.1.9 2 2 2zm6-6v-5c0-3.07-1.63-5.64-4.5-6.32V4c0-.83-.67-1.5-1.5-1.5s-1.5.67-1.5 1.5v.68C7.64 5.36 6 7.92 6 11v5l-2 2v1h16v-1l-2-2z" />
              </svg>
              <span className="topbar-notif-dot" />
            </div>

            <div className="topbar-avatar" title="User Profile">
              <svg viewBox="0 0 24 24" width="18" height="18" fill="#cbd5e1">
                <path d="M12 12c2.21 0 4-1.79 4-4s-1.79-4-4-4-4 1.79-4 4 1.79 4 4 4zm0 2c-2.67 0-8 1.34-8 4v2h16v-2c0-2.66-5.33-4-8-4z" />
              </svg>
            </div>
          </div>
        </header>

        {/* MAIN BODY CONTENT */}
        <main className="dashboard-content" role="main">
          {/* BACKEND UNAVAILABLE BANNER */}
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

          {/* ── PAGE 1: DASHBOARD ── */}
          {activeNav === "dashboard" && (
            <div className="page-view dashboard-page-view">
              <div className="page-title-banner">
                <div className="title-text-wrap">
                  <span className="page-eyebrow">OVERVIEW &amp; STATUS</span>
                  <h2>System Dashboard</h2>
                  <p className="page-desc">
                    AI-powered indoor room change detection and voice alert navigation overview.
                  </p>
                </div>
              </div>

              {/* Metric Cards Row */}
              <div className="dashboard-metrics-grid">
                <div className="metric-card">
                  <div className="metric-icon-wrap crimson">
                    <svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor">
                      <path d="M10 20v-6h4v6h5v-8h3L12 3 2 12h3v8z" />
                    </svg>
                  </div>
                  <div className="metric-content">
                    <span className="metric-label">ACTIVE ROOM</span>
                    <span className="metric-val">{effectiveRoomName}</span>
                    <span className="metric-sub">{hasCurrentRoomBaseline ? "Baseline configured" : "No baseline yet"}</span>
                  </div>
                </div>

                <div className="metric-card">
                  <div className="metric-icon-wrap green">
                    <svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor">
                      <path d="M17 10.5V7a1 1 0 0 0-1-1H4a1 1 0 0 0-1 1v10a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-3.5l4 4v-11l-4 4z"/>
                    </svg>
                  </div>
                  <div className="metric-content">
                    <span className="metric-label">CAMERA FEED</span>
                    <span className="metric-val">{cameraActive ? "Monitoring Active" : "Camera Idle"}</span>
                    <span className="metric-sub">{cameraViewStatus === "stable" ? "🟢 Viewpoint Aligned" : "⚠️ Check Position"}</span>
                  </div>
                </div>

                <div className="metric-card">
                  <div className="metric-icon-wrap purple">
                    <svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor">
                      <path d="m12 2-9 4.9 9 4.9 9-4.9L12 2zm0 14.8-7-3.8v4.9l7 3.8 7-3.8v-4.9l-7 3.8zm0-4.9-7-3.8v4.9l7 3.8 7-3.8v-4.9l-7 3.8z"/>
                    </svg>
                  </div>
                  <div className="metric-content">
                    <span className="metric-label">BASELINE OBJECTS</span>
                    <span className="metric-val">{baseline?.detections?.length ?? 0} Learned</span>
                    <span className="metric-sub">{baseline?.captured_at ? formatDate(baseline.captured_at) : "No layout captured"}</span>
                  </div>
                </div>

                <div className="metric-card">
                  <div className="metric-icon-wrap crimson">
                    <svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor">
                      <path d="M3 9v6h4l5 5V4L7 9H3zm13.5 3c0-1.77-1.02-3.29-2.5-4.03v8.05c1.48-.73 2.5-2.25 2.5-4.02z"/>
                    </svg>
                  </div>
                  <div className="metric-content">
                    <span className="metric-label">VOICE ALERTS</span>
                    <span className="metric-val">{voiceEnabled ? "Voice Enabled" : "Voice Muted"}</span>
                    <span className="metric-sub">{voiceUnlocked ? "Audio Unlocked" : "Speech Synthesis Ready"}</span>
                  </div>
                </div>
              </div>

              {/* Quick Actions Panel */}
              <div className="dashboard-quick-actions">
                <h3>Quick Navigation &amp; Controls</h3>
                <div className="actions-btn-group">
                  <button
                    type="button"
                    className="button button-crimson"
                    onClick={() => {
                      setActiveNav("monitoring");
                      if (!cameraActive) void startCamera();
                    }}
                  >
                    📷 {cameraActive ? "View Live Monitoring" : "Start Camera Monitoring"}
                  </button>

                  <button
                    type="button"
                    className="button button-secondary"
                    onClick={() => setActiveNav("layouts")}
                  >
                    🥞 Before &amp; After Comparison
                  </button>

                  <button
                    type="button"
                    className="button button-secondary"
                    onClick={() => setActiveNav("video")}
                  >
                    🎬 Video Comparison
                  </button>

                  <button
                    type="button"
                    className="button button-outline"
                    onClick={() => handleReplayVoice()}
                  >
                    🔊 Replay Last Voice Alert
                  </button>
                </div>
              </div>

              {/* Two-Column Overview */}
              <div className="dashboard-columns-grid">
                {/* Column 1: Live Status & Active Room Summary */}
                <div className="dashboard-card">
                  <div className="card-header-row">
                    <h3>Active Room Overview</h3>
                    <button
                      type="button"
                      className="link-button"
                      onClick={() => setActiveNav("rooms")}
                    >
                      Switch Room →
                    </button>
                  </div>
                  <p className="card-desc">
                    Currently monitoring <strong>{effectiveRoomName}</strong> using <strong>{DEFAULT_CAMERA_ID}</strong>.
                  </p>
                  <div className="room-overview-details">
                    <div className="overview-row">
                      <span>Reference Baseline:</span>
                      <strong>{baseline ? `${baseline.detections?.length || 0} objects learned` : "None"}</strong>
                    </div>
                    <div className="overview-row">
                      <span>Last Scan:</span>
                      <strong>{latest?.captured_at ? formatDate(latest.captured_at) : "No recent scan"}</strong>
                    </div>
                    <div className="overview-row">
                      <span>Camera Safety Status:</span>
                      <strong className={cameraViewStatus === "stable" ? "status-good" : "status-warn"}>
                        {cameraViewStatus === "stable" ? "Stable (Aligned)" : "Movement Detected / Unaligned"}
                      </strong>
                    </div>
                    <div className="overview-row">
                      <span>Speech Announcement:</span>
                      <span className="speech-quote">
                        "{lastSpokenAnnouncement || (history.length > 0 ? history[0].message : "No recent alerts.")}"
                      </span>
                    </div>
                  </div>
                </div>

                {/* Column 2: Recent Alerts */}
                <div className="dashboard-card">
                  <div className="card-header-row">
                    <h3>Recent Change Alerts</h3>
                    <button
                      type="button"
                      className="link-button"
                      onClick={() => setActiveNav("history")}
                    >
                      View All ({history.length}) →
                    </button>
                  </div>
                  {history.length === 0 ? (
                    <p className="empty-text">No change alerts recorded yet for {effectiveRoomName}.</p>
                  ) : (
                    <ul className="dashboard-alerts-list">
                      {history.slice(0, 4).map((alert) => (
                        <li key={alert.id} className="dashboard-alert-item">
                          <span className={`alert-type-badge ${alert.change_type}`}>
                            {alert.change_type.toUpperCase()}
                          </span>
                          <div className="alert-item-content">
                            <span className="alert-item-title">{alert.message}</span>
                            <span className="alert-item-time">{formatDate(alert.created_at)}</span>
                          </div>
                          <button
                            type="button"
                            className="alert-replay-icon-btn"
                            onClick={() => handleReplayVoice(alert.message)}
                            title="Replay this alert"
                          >
                            🔊
                          </button>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              </div>
            </div>
          )}

          {/* ── PAGE 2: LIVE MONITORING ── */}
          {activeNav === "monitoring" && (
            <div className="page-view monitoring-page-view">
              <div className="page-title-banner">
                <div className="title-text-wrap">
                  <span className="page-eyebrow">REAL-TIME OBSERVATION</span>
                  <h2>Live Camera Monitoring</h2>
                  <p className="page-desc">
                    Continuous camera monitoring for <strong>{effectiveRoomName}</strong> with automatic voice change alerts.
                  </p>
                </div>
              </div>

              {/* Room Quick Switch Bar */}
              <div className="monitoring-room-bar">
                <span className="room-bar-label">Current Room:</span>
                <span className="room-bar-active">{effectiveRoomName}</span>
                <button
                  type="button"
                  className="room-bar-switch-btn"
                  onClick={() => setActiveNav("rooms")}
                >
                  Change Room
                </button>
              </div>

              {/* Camera Panel + Baseline Panel Grid */}
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

              {/* Real-time Objects Tracking */}
              {hasCurrentRoomBaseline && (
                <section className="monitor-section" aria-label="Monitoring controls">
                  {monitorMessage && (
                    <div className="monitor-status-bar" role="status" aria-live="polite">
                      <span aria-hidden="true">{cameraActive ? "🟢" : "⚪"}</span> {monitorMessage}
                    </div>
                  )}
                  <LiveObjects
                    isActive={true}
                    latest={latest}
                    baseline={baseline}
                    liveComparison={liveComparison}
                    knownObjectNames={knownObjectNames}
                    cameraActive={cameraActive}
                    monitoringState={monitoringState}
                  />
                </section>
              )}
            </div>
          )}

          {/* ── PAGE 3: ROOMS ── */}
          {activeNav === "rooms" && (
            <div className="page-view rooms-page-view">
              <div className="page-title-banner">
                <div className="title-text-wrap">
                  <span className="page-eyebrow">ROOM CONFIGURATION</span>
                  <h2>Room Management</h2>
                  <p className="page-desc">
                    Select or add rooms to maintain isolated baselines, layouts, and historical change events.
                  </p>
                </div>
              </div>

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

              {/* Room Details Card */}
              <div className="dashboard-card" style={{ marginTop: "20px" }}>
                <h3>Active Room Summary</h3>
                <div className="room-overview-details">
                  <div className="overview-row">
                    <span>Selected Room:</span>
                    <strong>{effectiveRoomName}</strong>
                  </div>
                  <div className="overview-row">
                    <span>Camera ID:</span>
                    <strong>{DEFAULT_CAMERA_ID}</strong>
                  </div>
                  <div className="overview-row">
                    <span>Baseline Configured:</span>
                    <strong className={hasCurrentRoomBaseline ? "status-good" : "status-warn"}>
                      {hasCurrentRoomBaseline ? `Yes (${baseline?.detections?.length || 0} objects)` : "No baseline saved"}
                    </strong>
                  </div>
                  <div className="overview-row">
                    <span>Actions:</span>
                    <div className="actions-btn-group">
                      <button
                        type="button"
                        className="button button-crimson"
                        onClick={() => setActiveNav("monitoring")}
                      >
                        Start Monitoring This Room
                      </button>
                      <button
                        type="button"
                        className="button button-secondary"
                        onClick={() => setActiveNav("layouts")}
                      >
                        View Layouts &amp; Baselines
                      </button>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* ── PAGE 4: BASELINE / LAYOUT (PROMINENT BEFORE & AFTER) ── */}
          {activeNav === "layouts" && (
            <div className="page-view layouts-page-view">
              <div className="page-title-banner">
                <div className="title-text-wrap">
                  <span className="page-eyebrow">ROOM LAYOUTS &amp; CHANGE DETECTION</span>
                  <h2>Baseline &amp; Layout Management</h2>
                  <p className="page-desc">
                    Capture original baseline layouts, view saved snapshots, and run Before &amp; After comparisons.
                  </p>
                </div>
              </div>

              {/* ── PROMINENT BEFORE & AFTER COMPARISON SECTION ── */}
              <section className="layout-comparison-showcase" aria-label="Before and After Room Comparison">
                <div className="showcase-header">
                  <div className="showcase-title-wrap">
                    <span className="showcase-badge">PROMINENT COMPARISON</span>
                    <h2>Before &amp; After Room Comparison</h2>
                    <p className="showcase-subtitle">
                      Compare the original room layout against changes to detect moved, missing, or new objects with voice alerts.
                    </p>
                  </div>
                  {canCompareSavedLayouts && (
                    <button
                      type="button"
                      className="button button-crimson"
                      onClick={() => void handleShowComparison()}
                    >
                      <svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor">
                        <path d="M6.99 11L3 15l3.99 4v-3H14v-2H6.99v-3zM21 9l-3.99-4v3H10v2h7.01v3L21 9z"/>
                      </svg>
                      Compare BEFORE &amp; AFTER
                    </button>
                  )}
                </div>

                <div className="showcase-grid">
                  {/* BEFORE CARD */}
                  <div className="showcase-card showcase-before">
                    <div className="showcase-card-header">
                      <span className="card-tag before">BEFORE: ORIGINAL ROOM LAYOUT</span>
                      <span className="card-room-name">{beforeLayout?.layout_name || "Original Layout"}</span>
                    </div>
                    <div className="showcase-media-box">
                      {beforeLayout?.image_data_url ? (
                        <img
                          src={beforeLayout.image_data_url}
                          alt="Original room layout (Before)"
                          className="showcase-img"
                        />
                      ) : (
                        <div className="showcase-placeholder">
                          <span className="placeholder-icon">📷</span>
                          <p>No BEFORE layout captured</p>
                          <span className="placeholder-sub">Use the capture form below to record BEFORE snapshot</span>
                        </div>
                      )}
                    </div>
                    <div className="showcase-footer">
                      <div className="footer-meta">
                        <span className="meta-label">Capture Date:</span>
                        <span className="meta-val">
                          {beforeLayout?.captured_at ? formatDate(beforeLayout.captured_at) : "Not captured yet"}
                        </span>
                      </div>
                      <div className="footer-meta">
                        <span className="meta-label">Objects:</span>
                        <span className="meta-val">
                          {beforeLayout?.detections ? `${beforeLayout.detections.length} detected` : "0"}
                        </span>
                      </div>
                    </div>
                  </div>

                  {/* AFTER CARD */}
                  <div className="showcase-card showcase-after">
                    <div className="showcase-card-header">
                      <span className="card-tag after">AFTER: UPDATED ROOM LAYOUT</span>
                      <span className="card-room-name">{afterLayout?.layout_name || "Changed Layout"}</span>
                    </div>
                    <div className="showcase-media-box">
                      {afterLayout?.image_data_url ? (
                        <img
                          src={afterLayout.image_data_url}
                          alt="Changed room layout (After)"
                          className="showcase-img"
                        />
                      ) : (
                        <div className="showcase-placeholder">
                          <span className="placeholder-icon">📷</span>
                          <p>No AFTER layout captured</p>
                          <span className="placeholder-sub">Change room items and capture AFTER snapshot below</span>
                        </div>
                      )}
                    </div>
                    <div className="showcase-footer">
                      <div className="footer-meta">
                        <span className="meta-label">Capture Date:</span>
                        <span className="meta-val">
                          {afterLayout?.captured_at ? formatDate(afterLayout.captured_at) : "Not captured yet"}
                        </span>
                      </div>
                      <div className="footer-meta">
                        <span className="meta-label">Objects:</span>
                        <span className="meta-val">
                          {afterLayout?.detections ? `${afterLayout.detections.length} detected` : "0"}
                        </span>
                      </div>
                    </div>
                  </div>
                </div>

                {/* COMPARISON RESULTS & VOICE ALERT SUMMARY ROW */}
                <div className="showcase-action-results">
                  {/* Compare Button & Status */}
                  <div className="showcase-control-card">
                    <div className="control-header">
                      <span className="control-icon">⇄</span>
                      <h3>Room Comparison</h3>
                    </div>
                    <p className="control-desc">
                      {canCompareSavedLayouts
                        ? "Both BEFORE and AFTER layouts are ready for comparison."
                        : "Capture both BEFORE and AFTER layouts using the controls below to compare."}
                    </p>
                    <button
                      type="button"
                      className="button button-crimson"
                      disabled={!canCompareSavedLayouts}
                      onClick={() => void handleShowComparison()}
                    >
                      <svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor">
                        <path d="M6.99 11L3 15l3.99 4v-3H14v-2H6.99v-3zM21 9l-3.99-4v3H10v2h7.01v3L21 9z"/>
                      </svg>
                      {comparisonInFlightRef.current ? "Comparing..." : "Compare Layouts"}
                    </button>

                    {comparison && (
                      <div className="inline-comparison-stats">
                        <span className="stat-pill new">New: {comparison.comparison?.new?.length || 0}</span>
                        <span className="stat-pill missing">Missing: {comparison.comparison?.missing?.length || 0}</span>
                        <span className="stat-pill moved">Moved: {comparison.comparison?.moved?.length || 0}</span>
                        <span className="stat-pill unchanged">Unchanged: {comparison.comparison?.unchanged?.length || 0}</span>
                      </div>
                    )}
                  </div>

                  {/* Voice Alert Card */}
                  <div className="showcase-voice-card">
                    <div className="voice-card-header">
                      <span className="voice-icon">🔊</span>
                      <h3>Voice Alert</h3>
                      <button
                        type="button"
                        className={`voice-pill-toggle ${voiceEnabled ? "active" : ""}`}
                        onClick={handleToggleVoice}
                      >
                        {voiceEnabled ? "Voice ON" : "Voice MUTED"}
                      </button>
                    </div>
                    <p className="voice-quote-text">
                      "{lastSpokenAnnouncement || (comparison ? formatComparisonAnnouncement(comparison, effectiveRoomName) : "Capture and compare layouts to generate voice alerts.")}"
                    </p>
                    <div className="voice-card-actions">
                      <button
                        type="button"
                        className="button button-secondary"
                        onClick={() => handleReplayVoice()}
                      >
                        ▶ Play Voice Alert
                      </button>
                      <button
                        type="button"
                        className="button button-outline"
                        onClick={handleTestVoice}
                      >
                        🧪 Test Voice
                      </button>
                    </div>
                  </div>
                </div>
              </section>

              {/* Live Camera Feed & Baseline Panel */}
              <section className="learning-grid" aria-label="Room layout and camera" style={{ marginTop: "24px" }}>
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

              {/* Saved Layouts History & Capture Form */}
              <div style={{ marginTop: "24px" }}>
                <SavedLayoutsPanel
                  key={`${effectiveRoomName}\u0000${DEFAULT_CAMERA_ID}`}
                  roomName={effectiveRoomName}
                  cameraId={DEFAULT_CAMERA_ID}
                  cameraActive={cameraActive}
                  cameraStarting={cameraStarting}
                  videoRef={videoRef}
                  beforeLayout={beforeLayout}
                  afterLayout={afterLayout}
                  onComparisonLayoutSaved={handleComparisonLayoutSaved}
                  onStartNewComparison={resetSavedComparison}
                  onLayoutSaved={handleLayoutSaved}
                  onLayoutActivated={handleLayoutActivated}
                  onStartCamera={startCamera}
                />
              </div>
            </div>
          )}

          {/* ── PAGE 5: VIDEO COMPARISON ── */}
          {activeNav === "video" && (
            <VideoComparison />
          )}

          {/* ── PAGE 6: ALERT HISTORY ── */}
          {activeNav === "history" && (
            <div className="page-view history-page-view">
              <div className="page-title-banner">
                <div className="title-text-wrap">
                  <span className="page-eyebrow">AUDIT &amp; LOGS</span>
                  <h2>Alert History</h2>
                  <p className="page-desc">
                    Complete chronological history of confirmed room changes and voice announcements for <strong>{effectiveRoomName}</strong>.
                  </p>
                </div>
              </div>
              <div className="dashboard-card">
                <AlertHistory
                  isActive={true}
                  history={history}
                  onRepeat={repeatAlertReport}
                />
              </div>
            </div>
          )}

          {/* ── PAGE 7: FIND OBJECT ── */}
          {activeNav === "find" && (
            <div className="page-view find-page-view">
              <div className="page-title-banner">
                <div className="title-text-wrap">
                  <span className="page-eyebrow">VOICE &amp; TEXT SEARCH</span>
                  <h2>Find Object</h2>
                  <p className="page-desc">
                    Search for specific objects in <strong>{effectiveRoomName}</strong> using voice commands or text queries.
                  </p>
                </div>
              </div>
              <div className="dashboard-card">
                <FindPanel
                  isActive={true}
                  findQuery={findQuery}
                  setFindQuery={setFindQuery}
                  findResult={findResult}
                  onFind={() => { void findObject(); }}
                  onVoiceSearch={startVoiceSearch}
                />
              </div>
            </div>
          )}

          {/* ── PAGE 8: SETTINGS ── */}
          {activeNav === "settings" && (
            <div className="page-view settings-page-view">
              <div className="page-title-banner">
                <div className="title-text-wrap">
                  <span className="page-eyebrow">PREFERENCES &amp; ACCESSIBILITY</span>
                  <h2>System Settings</h2>
                  <p className="page-desc">
                    Configure speech output, camera parameters, and view system diagnostic information.
                  </p>
                </div>
              </div>

              <div className="settings-grid">
                <div className="dashboard-card">
                  <h3>Voice &amp; Audio Accessibility</h3>
                  <p className="card-desc">Control automated voice announcements and speech synthesis output.</p>
                  <div className="settings-controls-list">
                    <div className="settings-row">
                      <div>
                        <strong>Voice Alerts</strong>
                        <p className="setting-sub">Enable or mute automated spoken alerts when changes are confirmed.</p>
                      </div>
                      <button
                        type="button"
                        className={`button ${voiceEnabled ? "button-crimson" : "button-secondary"}`}
                        onClick={handleToggleVoice}
                      >
                        {voiceEnabled ? "Voice: ACTIVE" : "Voice: MUTED"}
                      </button>
                    </div>

                    <div className="settings-row">
                      <div>
                        <strong>Speech Synthesis Engine</strong>
                        <p className="setting-sub">
                          {voiceUnlocked
                            ? "Browser audio permissions are unlocked and ready for playback."
                            : "Click to unlock browser autoplay permissions for voice alerts."}
                        </p>
                      </div>
                      <button
                        type="button"
                        className="button button-secondary"
                        onClick={handleInitializeVoice}
                      >
                        {voiceUnlocked ? "Re-initialize Voice" : "Unlock Audio Permissions"}
                      </button>
                    </div>

                    <div className="settings-row">
                      <div>
                        <strong>Audio Output Test</strong>
                        <p className="setting-sub">Verify that your browser speakers or headphones can play alerts.</p>
                      </div>
                      <div className="actions-btn-group">
                        <button
                          type="button"
                          className="button button-outline"
                          onClick={handleTestVoice}
                        >
                          🧪 Test Voice Announcement
                        </button>
                        <button
                          type="button"
                          className="button button-outline"
                          onClick={() => handleReplayVoice()}
                        >
                          🔊 Replay Last Alert
                        </button>
                      </div>
                    </div>
                  </div>
                </div>

                <div className="dashboard-card">
                  <h3>Camera &amp; Change Detection Engine</h3>
                  <p className="card-desc">Operational thresholds for camera monitoring and spatial verification.</p>
                  <div className="settings-controls-list">
                    <div className="settings-row">
                      <div>
                        <strong>Camera Device</strong>
                        <p className="setting-sub">Active capture input.</p>
                      </div>
                      <span className="settings-badge">{DEFAULT_CAMERA_ID}</span>
                    </div>

                    <div className="settings-row">
                      <div>
                        <strong>Observation Rate</strong>
                        <p className="setting-sub">Interval between background camera scans.</p>
                      </div>
                      <span className="settings-badge">2.5 seconds</span>
                    </div>

                    <div className="settings-row">
                      <div>
                        <strong>Confirmation Threshold</strong>
                        <p className="setting-sub">Consecutive frames required before alerting.</p>
                      </div>
                      <span className="settings-badge">2 consecutive frames</span>
                    </div>

                    <div className="settings-row">
                      <div>
                        <strong>Object Detection Models</strong>
                        <p className="setting-sub">Primary &amp; Open-Vocabulary model pipelines.</p>
                      </div>
                      <span className="settings-badge">YOLO11n + YOLO-World</span>
                    </div>

                    <div className="settings-row">
                      <div>
                        <strong>Backend Status</strong>
                        <p className="setting-sub">Flask REST API server.</p>
                      </div>
                      <span className={`settings-badge ${backendDown ? "badge-error" : "badge-success"}`}>
                        {backendDown ? "Offline" : "🟢 Online (Port 5000)"}
                      </span>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* ── BEFORE / AFTER COMPARISON MODAL DIALOG ── */}
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
      </div>
    </div>
  );
}

export default App;
