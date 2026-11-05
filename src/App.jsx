import { useCallback, useEffect, useRef, useState } from "react";
import "./App.css";

const PRESET_ROOMS = ["Bedroom", "Kitchen", "Living room", "Bathroom", "Other"];
const DEFAULT_ROOM = "Living room";
const OBSERVATION_INTERVAL_MS = 2500;
// AbortController timeout for baseline fetches (ms)
const BASELINE_FETCH_TIMEOUT_MS = 10000;

async function readJson(response) {
  // Guard against non-JSON responses (e.g. HTML error pages from Flask/proxy)
  const contentType = response.headers.get("content-type") || "";
  if (!contentType.includes("application/json")) {
    throw new Error(`Server error ${response.status} — check Flask is running at http://127.0.0.1:5000`);
  }
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.error || `Request failed (${response.status})`);
  }
  return payload;
}

// Capture a JPEG data-URL from a video element, guaranteed to be JPEG.
// Uses an offscreen canvas; if the browser produces PNG instead of JPEG,
// re-encodes via a blob URL (async) to force JPEG.
async function captureJpegFromVideo(video, quality = 0.82) {
  const offscreen = document.createElement("canvas");
  const scale = Math.min(1, 1280 / video.videoWidth, 720 / video.videoHeight);
  offscreen.width = Math.round(video.videoWidth * scale);
  offscreen.height = Math.round(video.videoHeight * scale);
  const ctx = offscreen.getContext("2d");
  if (!ctx) throw new Error("Could not create canvas context from webcam frame.");
  ctx.drawImage(video, 0, 0, offscreen.width, offscreen.height);
  const dataUrl = offscreen.toDataURL("image/jpeg", quality);
  if (dataUrl.startsWith("data:image/jpeg;base64,")) return dataUrl;

  // Browser produced PNG — convert using a Blob and createObjectURL so the
  // image is fully decoded before we draw it onto the fallback canvas.
  return new Promise((resolve, reject) => {
    offscreen.toBlob((blob) => {
      if (!blob) { reject(new Error("Canvas toBlob failed.")); return; }
      const url = URL.createObjectURL(blob);
      const img = new Image();
      img.onload = () => {
        URL.revokeObjectURL(url);
        const fb = document.createElement("canvas");
        fb.width = offscreen.width;
        fb.height = offscreen.height;
        const ctx2 = fb.getContext("2d");
        ctx2.drawImage(img, 0, 0);
        const jpeg = fb.toDataURL("image/jpeg", quality);
        if (!jpeg.startsWith("data:image/jpeg;base64,")) {
          reject(new Error("Browser cannot produce a JPEG from the webcam. Try Chrome or Edge."));
        } else {
          resolve(jpeg);
        }
      };
      img.onerror = () => { URL.revokeObjectURL(url); reject(new Error("Could not re-encode webcam frame as JPEG.")); };
      img.src = url;
    }, "image/png");
  });
}

function formatDate(value) {
  return new Date(value).toLocaleString();
}

function objectLabel(object) {
  return `${object.class_name} ${object.instance_number}`;
}

// Draw bounding boxes on a canvas over an image
function DetectionOverlay({ imageUrl, detections, label }) {
  const canvasRef = useRef(null);
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !imageUrl) return;
    const img = new Image();
    img.onload = () => {
      const ctx = canvas.getContext("2d");
      canvas.width = img.naturalWidth;
      canvas.height = img.naturalHeight;
      ctx.drawImage(img, 0, 0);
      if (detections && detections.length) {
        detections.forEach((det) => {
          const x = det.x1 * img.naturalWidth;
          const y = det.y1 * img.naturalHeight;
          const w = (det.x2 - det.x1) * img.naturalWidth;
          const h = (det.y2 - det.y1) * img.naturalHeight;
          ctx.strokeStyle = "#2d9c5e";
          ctx.lineWidth = 2;
          ctx.strokeRect(x, y, w, h);
          ctx.fillStyle = "rgba(45,156,94,0.85)";
          const text = `${det.class_name} ${Math.round(det.confidence * 100)}%`;
          ctx.font = `bold ${Math.max(11, img.naturalWidth / 60)}px sans-serif`;
          const tw = ctx.measureText(text).width + 6;
          ctx.fillRect(x, y - Math.max(16, img.naturalHeight / 35), tw, Math.max(16, img.naturalHeight / 35));
          ctx.fillStyle = "#fff";
          ctx.fillText(text, x + 3, y - 3);
        });
      }
    };
    img.src = imageUrl;
  }, [imageUrl, detections]);
  return (
    <div className="overlay-wrapper">
      <p className="overlay-label">{label}</p>
      <canvas
        ref={canvasRef}
        className="detection-canvas"
        aria-label={label}
        role="img"
      />
    </div>
  );
}

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
      if (
        !speechSupportedRef.current ||
        !("speechSynthesis" in window) ||
        typeof window.SpeechSynthesisUtterance !== "function"
      ) {
        recordPlayback(event, "unavailable", "Speech playback is unavailable in this browser.");
        return;
      }
      const utterance = new window.SpeechSynthesisUtterance(event.message);
      utterance.rate = 0.92;
      utterance.onend = () => recordPlayback(event, "spoken");
      utterance.onerror = (speechEvent) => {
        const reason = speechEvent.error || "Browser speech playback failed.";
        recordPlayback(event, "failed", reason);
        setMonitorMessage(`Voice alert could not be played: ${reason}`);
      };
      window.speechSynthesis.speak(utterance);
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
      if ("speechSynthesis" in window) window.speechSynthesis.cancel();
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

      speechSupportedRef.current =
        "speechSynthesis" in window && typeof window.SpeechSynthesisUtterance === "function";
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
    if (!("speechSynthesis" in window)) {
      setError("Speech playback is unavailable in this browser.");
      return;
    }
    const report = history.slice(0, 5).map((event) => event.message).join(" ");
    window.speechSynthesis.cancel();
    window.speechSynthesis.speak(new window.SpeechSynthesisUtterance(report));
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
      if ("speechSynthesis" in window) {
        const utterance = new window.SpeechSynthesisUtterance(result.message);
        utterance.onerror = (speechEvent) => {
          const reason = speechEvent.error || "Browser speech playback failed.";
          setMonitorMessage(`Object-finding voice response could not be played: ${reason}`);
        };
        window.speechSynthesis.speak(utterance);
      }
    } catch (findError) {
      setError(findError.message);
    }
  }

  function startVoiceSearch() {
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRecognition) {
      setError("Voice recognition is unavailable in this browser. Enter an object name instead.");
      return;
    }
    setError("");
    const recognition = new SpeechRecognition();
    recognition.lang = "en-US";
    recognition.continuous = false;
    recognition.interimResults = false;
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
      <section className="room-selector-section" aria-label="Room selection">
        <div className="room-selector-card">
          <h2 className="room-selector-heading">
            <span aria-hidden="true">🏠</span> Select Room
          </h2>
          <div className="room-pills" role="group" aria-label="Preset rooms">
            {PRESET_ROOMS.map((room) => (
              <button
                key={room}
                className={`room-pill ${!isCustomRoom && roomName === room ? "room-pill-active" : ""}`}
                onClick={() => {
                  if (roomName === room && !isCustomRoom) return; // already selected
                  if (cameraActive) stopCamera();
                  setIsCustomRoom(false);
                  setRoomName(room);
                  setError("");
                  setFindResult("");
                  setBaselineLoading(true);
                }}
                aria-pressed={!isCustomRoom && roomName === room}
                aria-label={`Select ${room}`}
              >
                {room}
              </button>
            ))}
            <button
              className={`room-pill ${isCustomRoom ? "room-pill-active" : ""}`}
              onClick={() => {
                if (cameraActive) stopCamera();
                setIsCustomRoom(true);
                setError("");
                setFindResult("");
                setBaselineLoading(true);
              }}
              aria-pressed={isCustomRoom}
              aria-label="Enter custom room name"
            >
              Custom
            </button>
          </div>
          {isCustomRoom && (
            <label className="room-field custom-room-field">
              <span>Custom room name</span>
              <input
                aria-label="Enter custom room name"
                maxLength={80}
                onChange={(e) => {
                  const next = e.target.value;
                  if (next === customRoomName) return;
                  setCustomRoomName(next);
                  setError("");
                  setFindResult("");
                  setBaselineLoading(true);
                }}
                placeholder="e.g. Study, Garage..."
                value={customRoomName}
                autoFocus
              />
            </label>
          )}
          {knownRooms.length > 0 && (
            <p className="known-rooms-note" aria-live="polite">
              Rooms with saved layouts:{" "}
              {knownRooms.map((r) => (
                <button
                  key={r.room_key}
                  className="known-room-link"
                  onClick={() => {
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
                  aria-label={`Switch to ${r.room_name} (${r.detection_count} objects)`}
                >
                  {r.room_name} ({r.detection_count})
                </button>
              ))}
            </p>
          )}
        </div>
      </section>

      {/* ── CAMERA + LAYOUT CAPTURE ── */}
      <section className="learning-grid" aria-label="Room layout and camera">
        <div className="panel camera-panel">
          <div className="panel-heading">
            <div>
              <p className="eyebrow">LIVE CAMERA</p>
              <h2 id="camera-heading">
                {effectiveRoomName || "Select a room"} — Camera
              </h2>
            </div>
            <span className={`status-pill ${cameraActive ? "is-live" : ""}`} aria-live="polite">
              <span aria-hidden="true" className="status-dot" />
              {cameraActive ? (baseline?.detections.length ? "Monitoring" : "Camera on") : "Camera off"}
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
                  onClick={startCamera}
                  aria-label="Start monitoring camera"
                >
                  {baseline?.detections.length ? "▶ Start Monitoring" : "▶ Start Webcam"}
                </button>
              ) : (
                <button
                  className="button button-secondary"
                  onClick={stopCamera}
                  aria-label="Stop monitoring camera"
                >
                  ⏹ Stop {baseline?.detections.length ? "Monitoring" : "Camera"}
                </button>
              )}

              <button
                className="button button-primary"
                disabled={!cameraActive || busy || !effectiveRoomName || hasCurrentRoomBaseline}
                onClick={() => captureLayout(false)}
                aria-label="Capture original room layout"
              >
                {busy ? "Saving layout..." : hasCurrentRoomBaseline ? "✓ Layout Saved" : "📷 Capture Original Layout"}
              </button>
            </div>

            {cameraActive && hasCurrentRoomBaseline && (
              <button
                className="relearn-button"
                disabled={busy}
                onClick={() => captureLayout(true)}
                aria-label="Replace saved layout with current view"
              >
                🔄 Re-capture layout (replaces saved baseline)
              </button>
            )}

            {hasCurrentRoomBaseline && latest && (
              <button
                className="compare-button"
                onClick={handleShowComparison}
                aria-label="View before and after comparison"
              >
                🔍 View Before &amp; After Comparison
              </button>
            )}
          </div>
          <canvas className="capture-canvas" ref={canvasRef} aria-hidden="true" />
        </div>

        {/* ── BASELINE / ORIGINAL LAYOUT ── */}
        <section className="panel memory-panel" aria-live="polite" aria-label="Saved original layout">
          <div className="panel-heading">
            <div>
              <p className="eyebrow">ORIGINAL LAYOUT</p>
              <h2>Saved arrangement</h2>
            </div>
            {hasCurrentRoomBaseline && <span className="saved-badge" aria-label="Layout saved">✓ Saved</span>}
          </div>

          {baselineLoading ? (
            <p className="empty-state" aria-live="polite">Loading saved room memory...</p>
          ) : hasCurrentRoomBaseline ? (
            <>
              <img
                alt={`Saved camera view of ${baseline.room_name}`}
                className="baseline-image"
                src={baseline.image_data_url}
              />
              <p className="saved-meta">
                {baseline.room_name} | Captured {formatDate(baseline.captured_at)}
              </p>
              <p className="detection-count">
                {baseline.detections.length} object{baseline.detections.length === 1 ? "" : "s"} recorded
              </p>
              {baseline.detections.length ? (
                <ul className="object-list" aria-label="Detected objects in baseline">
                  {baseline.detections.map((object) => (
                    <li
                      className="object-card"
                      key={`${object.class_name}-${object.instance_number}`}
                      aria-label={`${object.class_name}, zone: ${object.zone}, confidence ${Math.round(object.confidence * 100)}%`}
                    >
                      <span className="object-symbol" aria-hidden="true">
                        {object.class_name.slice(0, 1).toUpperCase()}
                      </span>
                      <span className="object-description">
                        <strong>{objectLabel(object)}</strong>
                        <span>{object.zone} | {Math.round(object.confidence * 100)}% confidence</span>
                      </span>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="empty-state">
                  No supported objects detected. Reframe camera and re-capture layout.
                </p>
              )}
              <p className="identity-note">
                Zones are approximate image regions. Object numbers are per-scan, not persistent identities.
              </p>
            </>
          ) : (
            <div className="empty-state">
              <span className="empty-icon" aria-hidden="true">
                <svg viewBox="0 0 24 24">
                  <path d="m3 10 9-7 9 7v11h-7v-7h-4v7H3z" />
                </svg>
              </span>
              <p>No saved layout for <strong>{effectiveRoomName || "this room"}</strong>.</p>
              <p>Start the webcam, point it at the room, and click <strong>Capture Original Layout</strong>.</p>
            </div>
          )}
        </section>
      </section>

      {/* ── BEFORE / AFTER COMPARISON MODAL ── */}
      {showComparison && comparison && (
        <div
          className="comparison-backdrop"
          role="dialog"
          aria-modal="true"
          aria-label="Before and after room comparison"
          onClick={(e) => { if (e.target === e.currentTarget) setShowComparison(false); }}
        >
          <div className="comparison-modal">
            <div className="comparison-header">
              <h2>Before &amp; After Comparison — {effectiveRoomName}</h2>
              <button
                className="close-button"
                onClick={() => setShowComparison(false)}
                aria-label="Close comparison"
              >
                ✕
              </button>
            </div>
            <div className="comparison-grid">
              <DetectionOverlay
                imageUrl={comparison.baseline?.image_data_url}
                detections={comparison.baseline?.detections}
                label={`Original layout — ${formatDate(comparison.baseline?.captured_at)}`}
              />
              <DetectionOverlay
                imageUrl={comparison.latest?.image_data_url}
                detections={comparison.latest?.detections}
                label={`Latest scan — ${comparison.latest ? formatDate(comparison.latest.captured_at) : "Not yet scanned"}`}
              />
            </div>
            {comparison.baseline && comparison.latest && (
              <div className="comparison-summary">
                <p>
                  <strong>Original:</strong> {comparison.baseline.detections.length} object{comparison.baseline.detections.length !== 1 ? "s" : ""}
                  &nbsp;|&nbsp;
                  <strong>Latest:</strong> {comparison.latest.detections.length} object{comparison.latest.detections.length !== 1 ? "s" : ""}
                </p>
              </div>
            )}
          </div>
        </div>
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
          <div
            id="tab-panel-monitor"
            role="tabpanel"
            className={`tab-panel ${activeTab !== "monitor" ? "tab-panel-hidden" : ""}`}
            aria-label="Live detected objects"
          >
            <div className="panel">
              <div className="panel-heading">
                <div>
                  <p className="eyebrow">LIVE OBSERVATIONS</p>
                  <h2>Latest detected objects</h2>
                </div>
                {cameraActive && <span className="saved-badge">Live scan</span>}
              </div>
              {latest?.detections?.length ? (
                <ul className="object-list latest-list" aria-label="Currently detected objects">
                  {latest.detections.map((object, index) => {
                    const isOutsideBaseline = !knownObjectNames.has(object.class_name) && cameraActive;
                    return (
                      <li
                        className={`object-card ${isOutsideBaseline ? "object-card-new" : ""}`}
                        key={`${object.class_name}-${object.instance_number}-${index}`}
                        aria-label={`${object.class_name}${isOutsideBaseline ? " — not in original layout" : ""}, zone: ${object.zone}`}
                      >
                        <span className="object-symbol" aria-hidden="true">
                          {object.class_name.slice(0, 1).toUpperCase()}
                        </span>
                        <span className="object-description">
                          <strong>{objectLabel(object)}{isOutsideBaseline ? " · New" : ""}</strong>
                          <span>{object.zone} | {Math.round(object.confidence * 100)}% confidence</span>
                        </span>
                      </li>
                    );
                  })}
                </ul>
              ) : (
                <p className="history-empty">
                  {latest
                    ? "No supported objects visible in the latest scan."
                    : "Start monitoring to show the latest reliable camera observations."}
                </p>
              )}
              {latest?.captured_at && (
                <p className="saved-meta">Last reliable scan: {formatDate(latest.captured_at)}</p>
              )}
            </div>
          </div>

          {/* ── HISTORY TAB ── */}
          <div
            id="tab-panel-history"
            role="tabpanel"
            className={`tab-panel ${activeTab !== "history" ? "tab-panel-hidden" : ""}`}
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
                  onClick={repeatAlertReport}
                  aria-label="Repeat recent alerts by voice"
                >
                  🔊 Repeat report
                </button>
              </div>
              {history.length ? (
                <ol className="history-list" aria-label="Change alert history list">
                  {history.map((event) => (
                    <li className="history-item" key={event.id}>
                      <span className={`change-badge change-${event.change_type}`} aria-label={`Change type: ${event.change_type}`}>
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

          {/* ── FIND OBJECT TAB ── */}
          <div
            id="tab-panel-find"
            role="tabpanel"
            className={`tab-panel ${activeTab !== "find" ? "tab-panel-hidden" : ""}`}
            aria-label="Find an object by voice or text"
          >
            <div className="panel">
              <div className="panel-heading">
                <div>
                  <p className="eyebrow">VOICE-ASSISTED FINDER</p>
                  <h2>Find an object</h2>
                </div>
              </div>
              <form
                className="finder-form"
                onSubmit={(event) => { event.preventDefault(); void findObject(); }}
                aria-label="Object search form"
              >
                <label className="room-field finder-field">
                  <span>Ask where an object was last seen</span>
                  <input
                    aria-label="Object name or question"
                    maxLength={80}
                    onChange={(event) => setFindQuery(event.target.value)}
                    placeholder="e.g. Where is my bag?"
                    value={findQuery}
                  />
                </label>
                <button className="button button-primary" type="submit" aria-label="Search for object">
                  🔎 Find object
                </button>
                <button
                  className="button button-secondary"
                  onClick={startVoiceSearch}
                  type="button"
                  aria-label="Ask where an object is using voice"
                >
                  🎤 Ask by voice
                </button>
              </form>
              {findResult && (
                <p className="finder-result" role="status" aria-live="polite">
                  {findResult}
                </p>
              )}
              <div className="finder-hint">
                <p>Supported objects: chair, bottle, bag, backpack, handbag, couch, dining table, suitcase, and more.</p>
              </div>
            </div>
          </div>
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
