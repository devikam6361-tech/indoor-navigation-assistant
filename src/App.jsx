import { useCallback, useEffect, useRef, useState } from "react";
import "./App.css";

const DEFAULT_ROOM = "Living room";
const OBSERVATION_INTERVAL_MS = 2500;

async function readJson(response) {
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.error || `Request failed (${response.status})`);
  }
  return payload;
}

function formatDate(value) {
  return new Date(value).toLocaleString();
}

function objectLabel(object) {
  return `${object.class_name} ${object.instance_number}`;
}

function App() {
  const videoRef = useRef(null);
  const canvasRef = useRef(null);
  const streamRef = useRef(null);
  const speechSupportedRef = useRef(false);
  const lastCameraStatusRef = useRef("");
  const [roomName, setRoomName] = useState(DEFAULT_ROOM);
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

  const loadBaseline = useCallback(async (name) => {
    const query = encodeURIComponent(name);
    const [baselineResponse, latestResponse] = await Promise.all([
      fetch(`/api/baseline?room_name=${query}`),
      fetch(`/api/latest?room_name=${query}`),
    ]);
    const [{ baseline: savedBaseline }, savedLatest] = await Promise.all([
      readJson(baselineResponse),
      readJson(latestResponse),
    ]);
    return { baseline: savedBaseline, latest: savedLatest.latest, history: savedLatest.history };
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
            ? {
                ...item,
                speech_status: status,
                speech_error: playbackError || null,
              }
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

  useEffect(() => {
    let cancelled = false;
    const name = roomName.trim() || DEFAULT_ROOM;

    loadBaseline(name)
      .then(({ baseline: savedBaseline, latest: savedLatest, history: savedHistory }) => {
        if (!cancelled) {
          setBaseline(savedBaseline);
          setLatest(savedLatest);
          setHistory(savedHistory);
        }
      })
      .catch((loadError) => {
        if (!cancelled) {
          setBaseline(null);
          setLatest(null);
          setHistory([]);
          setError(
            `${loadError.message}. Start the Flask service with python -m ai.server.`,
          );
        }
      })
      .finally(() => {
        if (!cancelled) {
          setBaselineLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [loadBaseline, roomName]);

  useEffect(
    () => () => {
      streamRef.current?.getTracks().forEach((track) => track.stop());
      if ("speechSynthesis" in window) {
        window.speechSynthesis.cancel();
      }
    },
    [],
  );

  useEffect(() => {
    if (
      !cameraActive ||
      !baseline ||
      !baseline.detections.length ||
      !videoRef.current ||
      !canvasRef.current
    ) {
      return undefined;
    }

    let requestInFlight = false;
    const controller = new AbortController();

    async function scanFrame() {
      const video = videoRef.current;
      const canvas = canvasRef.current;
      if (
        requestInFlight ||
        !video ||
        video.readyState < HTMLMediaElement.HAVE_CURRENT_DATA ||
        video.videoWidth === 0
      ) {
        return;
      }

      requestInFlight = true;
      try {
        const scale = Math.min(1, 1280 / video.videoWidth, 720 / video.videoHeight);
        canvas.width = Math.round(video.videoWidth * scale);
        canvas.height = Math.round(video.videoHeight * scale);
        const context = canvas.getContext("2d");
        if (!context) {
          throw new Error("Could not prepare a frame from the webcam.");
        }
        context.drawImage(video, 0, 0, canvas.width, canvas.height);

        const result = await readJson(
          await fetch("/api/observe", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              room_name: roomName.trim(),
              image: canvas.toDataURL("image/jpeg", 0.78),
            }),
            signal: controller.signal,
          }),
        );

        if (controller.signal.aborted) {
          return;
        }

        if (result.status !== lastCameraStatusRef.current) {
          lastCameraStatusRef.current = result.status;
          if (result.status === "camera_moved") {
            setMonitorMessage(
              "Camera view changed. Alerts are paused until you restore the learned viewpoint or explicitly relearn this room.",
            );
          } else if (result.status === "view_unverified") {
            setMonitorMessage(
              "Camera view could not be verified. Changes are not being announced to avoid false alerts.",
            );
          } else {
            setMonitorMessage(
              "Monitoring this camera view for confirmed changes. Alerts require repeated detections.",
            );
          }
        }

        if (result.latest) {
          setLatest(result.latest);
        }
        setHistory(result.history);
        for (const event of result.alerts) {
          speakAlert(event);
        }
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
  }, [baseline, cameraActive, roomName, speakAlert]);

  async function startCamera() {
    setError("");
    setNotice("");
    if (!hasCurrentRoomBaseline) {
      setError("Learn a baseline for this room before starting change monitoring.");
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: false,
        video: true,
      });
      streamRef.current = stream;
      videoRef.current.srcObject = stream;
      await videoRef.current.play();
      speechSupportedRef.current =
        "speechSynthesis" in window &&
        typeof window.SpeechSynthesisUtterance === "function";
      lastCameraStatusRef.current = "";
      setMonitorMessage(
        baseline.detections.length
          ? "Starting room monitoring..."
          : "Monitoring is paused because no supported objects were saved. Keep the camera fixed and use Relearn room after visible household objects are in view.",
      );
      setCameraActive(true);
    } catch (cameraError) {
      setError(
        cameraError.name === "NotAllowedError"
          ? "Camera access was denied. Allow camera access in your browser settings and try again."
          : `Could not start the webcam: ${cameraError.message}`,
      );
    }
  }

  function stopCamera() {
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
    if (videoRef.current) {
      videoRef.current.srcObject = null;
    }
    setCameraActive(false);
    setMonitorMessage("Monitoring is stopped.");
  }

  async function learnLayout(replace = false) {
    const name = roomName.trim();
    if (!name || !videoRef.current || videoRef.current.videoWidth === 0) {
      setError("Enter a room name and wait for the webcam image before learning.");
      return;
    }

    if (replace && !window.confirm(
      `Relearn the ${name} room? This explicitly replaces its saved baseline.`,
    )) {
      return;
    }

    setBusy(true);
    setError("");
    setNotice("");
    try {
      const video = videoRef.current;
      const canvas = canvasRef.current;
      const scale = Math.min(1, 1920 / video.videoWidth, 1080 / video.videoHeight);
      canvas.width = Math.round(video.videoWidth * scale);
      canvas.height = Math.round(video.videoHeight * scale);
      const context = canvas.getContext("2d");
      if (!context) {
        throw new Error("Could not prepare a frame from the webcam.");
      }
      context.drawImage(video, 0, 0, canvas.width, canvas.height);

      const result = await readJson(
        await fetch("/api/baseline", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            room_name: name,
            image: canvas.toDataURL("image/jpeg", 0.85),
            replace,
          }),
        }),
      );
      setBaseline(result.baseline);
      setLatest(null);
      setMonitorMessage("Baseline saved. Start the camera to monitor this room.");
      setNotice(
        `Saved ${result.baseline.detections.length} supported object${result.baseline.detections.length === 1 ? "" : "s"} in the ${name} baseline.`,
      );
      await loadHistory(name).catch((historyError) => {
        setError(`Baseline was saved, but alert history could not be refreshed: ${historyError.message}`);
      });
    } catch (saveError) {
      setError(saveError.message);
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
    const report = history
      .slice(0, 5)
      .map((event) => event.message)
      .join(" ");
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
        `/api/find?room_name=${encodeURIComponent(roomName.trim())}&object_name=${encodeURIComponent(search)}`,
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
      } else {
        setMonitorMessage("Text result is available, but speech playback is unsupported.");
      }
    } catch (findError) {
      setError(findError.message);
    }
  }

  function startVoiceSearch() {
    const SpeechRecognition =
      window.SpeechRecognition || window.webkitSpeechRecognition;
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
      setError(`Voice search failed: ${event.error}. You can enter the object name instead.`);
    };
    try {
      recognition.start();
    } catch (recognitionError) {
      setError(`Could not start voice search: ${recognitionError.message}`);
    }
  }

  const hasCurrentRoomBaseline =
    baseline &&
    baseline.room_name.toLowerCase() === roomName.trim().toLowerCase();
  const knownObjectNames = new Set(
    (baseline?.detections || []).map((item) => item.class_name),
  );

  return (
    <main className="app-shell">
      <header className="page-header">
        <p className="eyebrow">INDOOR NAVIGATION ASSISTANT</p>
        <h1>Learn your home layout</h1>
        <p className="intro">
          Save a camera-view memory of this room. Later scans can be compared
          with this baseline to identify changes.
        </p>
      </header>

      <section className="learning-grid" aria-label="Home layout learning">
        <div className="panel camera-panel">
          <div className="panel-heading">
            <div>
              <p className="eyebrow">FIXED VIEWPOINT</p>
              <h2>Room camera</h2>
            </div>
            <span className={`status-pill ${cameraActive ? "is-live" : ""}`}>
              <span aria-hidden="true" className="status-dot" />
              {cameraActive
                ? baseline?.detections.length
                  ? "Monitoring"
                  : "Camera on"
                : "Camera off"}
            </span>
          </div>

          <div className="camera-frame">
            <video ref={videoRef} autoPlay muted playsInline />
            {!cameraActive && (
              <div className="camera-placeholder">
                <span className="camera-icon" aria-hidden="true">
                  <svg viewBox="0 0 24 24">
                    <path d="M4 7h3l1.5-2h7L17 7h3v12H4z" />
                    <circle cx="12" cy="13" r="4" />
                  </svg>
                </span>
                <p>Start the webcam to preview and monitor this room</p>
                <p className="camera-hint">
                  Keep the camera fixed in its learned position.
                </p>
              </div>
            )}
          </div>

          <div className="camera-controls">
            <label className="room-field">
              <span>Room name</span>
              <input
                maxLength={80}
                onChange={(event) => {
                  if (cameraActive) {
                    stopCamera();
                  }
                  setRoomName(event.target.value);
                  setBaselineLoading(true);
                  setError("");
                  setFindResult("");
                }}
                placeholder="For example, Living room"
                value={roomName}
              />
            </label>
            <div className="button-row">
              {!cameraActive ? (
                <button
                  className="button button-secondary"
                  disabled={!hasCurrentRoomBaseline || baselineLoading}
                  onClick={startCamera}
                >
                  {baseline?.detections.length
                    ? "Start monitoring"
                    : "Start webcam"}
                </button>
              ) : (
                <button className="button button-secondary" onClick={stopCamera}>
                  {baseline?.detections.length ? "Stop monitoring" : "Stop camera"}
                </button>
              )}
              <button
                className="button button-primary"
                disabled={!cameraActive || busy || !roomName.trim() || hasCurrentRoomBaseline}
                onClick={() => learnLayout(false)}
              >
                {busy
                  ? "Learning layout..."
                  : hasCurrentRoomBaseline
                    ? "Layout already learned"
                    : "Learn Home Layout"}
              </button>
            </div>
            {cameraActive && hasCurrentRoomBaseline && (
              <button
                className="relearn-button"
                disabled={busy}
                onClick={() => learnLayout(true)}
              >
                Relearn room (replace saved baseline)
              </button>
            )}
          </div>
          <canvas className="capture-canvas" ref={canvasRef} />
        </div>

        <section className="panel memory-panel" aria-live="polite">
          <div className="panel-heading">
            <div>
              <p className="eyebrow">SAVED HOME MEMORY</p>
              <h2>Original arrangement</h2>
            </div>
            {hasCurrentRoomBaseline && (
              <span className="saved-badge">Saved</span>
            )}
          </div>

          {baselineLoading ? (
            <p className="empty-state">Loading saved room memory...</p>
          ) : hasCurrentRoomBaseline ? (
            <>
              <img
                alt={`Saved camera view of ${baseline.room_name}`}
                className="baseline-image"
                src={baseline.image_data_url}
              />
              <p className="saved-meta">
                {baseline.room_name} | Learned {formatDate(baseline.captured_at)}
              </p>
              <p className="detection-count">
                {baseline.detections.length} supported object
                {baseline.detections.length === 1 ? "" : "s"} recorded
              </p>
              {baseline.detections.length ? (
                <ul className="object-list">
                  {baseline.detections.map((object) => (
                    <li
                      className="object-card"
                      key={`${object.class_name}-${object.instance_number}`}
                    >
                      <span className="object-symbol" aria-hidden="true">
                        {object.class_name.slice(0, 1).toUpperCase()}
                      </span>
                      <span className="object-description">
                        <strong>{objectLabel(object)}</strong>
                        <span>
                          {object.zone} | {Math.round(object.confidence * 100)}%
                          confidence
                        </span>
                      </span>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="empty-state">
                  No supported household objects were detected, so this baseline
                  cannot yet identify moved or missing objects. Check the room
                  framing and lighting, then use Relearn room when objects are
                  visible.
                </p>
              )}
              <p className="identity-note">
                Locations are approximate image zones. Same-type numbers describe
                one scan, not persistent object identities.
              </p>
            </>
          ) : (
            <div className="empty-state">
              <span className="empty-icon" aria-hidden="true">
                <svg viewBox="0 0 24 24">
                  <path d="m3 10 9-7 9 7v11h-7v-7h-4v7H3z" />
                </svg>
              </span>
              <p>No saved layout for this room yet.</p>
              <p>Start the webcam and learn the usual arrangement.</p>
            </div>
          )}
        </section>
      </section>

      {hasCurrentRoomBaseline && (
        <section className="monitor-grid" aria-label="Room monitoring">
          <section className="panel finder-panel" aria-label="Object finder">
            <div className="panel-heading">
              <div>
                <p className="eyebrow">VOICE-ASSISTED FINDER</p>
                <h2>Find an object</h2>
              </div>
            </div>
            <form
              className="finder-form"
              onSubmit={(event) => {
                event.preventDefault();
                void findObject();
              }}
            >
              <label className="room-field finder-field">
                <span>Ask where an object was last seen</span>
                <input
                  maxLength={80}
                  onChange={(event) => setFindQuery(event.target.value)}
                  placeholder="For example, Where is my bag?"
                  value={findQuery}
                />
              </label>
              <button className="button button-primary" type="submit">
                Find object
              </button>
              <button
                className="button button-secondary"
                onClick={startVoiceSearch}
                type="button"
              >
                Ask by voice
              </button>
            </form>
            {findResult && (
              <p className="finder-result" role="status">
                {findResult}
              </p>
            )}
          </section>
          <section className="panel monitor-panel" aria-live="polite">
            <div className="panel-heading">
              <div>
                <p className="eyebrow">LIVE OBSERVATIONS</p>
                <h2>Latest detected objects</h2>
              </div>
              {cameraActive && <span className="saved-badge">Live scan</span>}
            </div>
            {monitorMessage && (
              <p className="monitor-status" role="status">
                {monitorMessage}
              </p>
            )}
            {latest?.detections?.length ? (
              <ul className="object-list latest-list">
                {latest.detections.map((object, index) => {
                  const isOutsideBaseline =
                    !knownObjectNames.has(object.class_name) &&
                    cameraActive;
                  return (
                    <li
                      className={`object-card ${isOutsideBaseline ? "object-card-new" : ""}`}
                      key={`${object.class_name}-${object.instance_number}-${index}`}
                    >
                      <span className="object-symbol" aria-hidden="true">
                        {object.class_name.slice(0, 1).toUpperCase()}
                      </span>
                      <span className="object-description">
                        <strong>{objectLabel(object)}{isOutsideBaseline ? " · Not in baseline" : ""}</strong>
                        <span>
                          {object.zone} | {Math.round(object.confidence * 100)}%
                          confidence
                        </span>
                      </span>
                    </li>
                  );
                })}
              </ul>
            ) : (
              <p className="history-empty">
                {latest
                  ? "No supported objects are visible in the latest scan."
                  : "Start monitoring to show the latest reliable camera observations."}
              </p>
            )}
            {latest?.captured_at && (
              <p className="saved-meta">
                Last reliable scan: {formatDate(latest.captured_at)}
              </p>
            )}
          </section>

          <section className="panel monitor-panel" aria-live="polite">
            <div className="panel-heading">
              <div>
                <p className="eyebrow">CONFIRMED CHANGES</p>
                <h2>Alert history</h2>
              </div>
              <button
                className="repeat-button"
                disabled={!history.length}
                onClick={repeatAlertReport}
              >
                Repeat report
              </button>
            </div>
            {history.length ? (
              <ol className="history-list">
                {history.map((event) => (
                  <li className="history-item" key={event.id}>
                    <span className={`change-badge change-${event.change_type}`}>
                      {event.change_type.startsWith("camera_view_")
                        ? "Camera status"
                        : event.change_type === "moved"
                          ? "Moved"
                          : event.change_type === "newly_observed"
                            ? "New"
                            : "Not visible"}
                    </span>
                    <p className="history-message">{event.message}</p>
                    <p className="history-meta">
                      {event.object_name} | {formatDate(event.created_at)}
                      {event.confidence !== null &&
                        ` | ${Math.round(event.confidence * 100)}% detection confidence`}
                    </p>
                    <p className="history-meta">
                      Voice:{" "}
                      {event.speech_status === "spoken"
                        ? "played"
                        : event.speech_status === "failed"
                          ? `failed${event.speech_error ? ` - ${event.speech_error}` : ""}`
                          : event.speech_status === "unavailable"
                            ? "unavailable"
                            : "pending"}
                    </p>
                  </li>
                ))}
              </ol>
            ) : (
              <p className="history-empty">
                No confirmed changes yet. Alerts are created only after a
                change appears in {3} consecutive reliable scans.
              </p>
            )}
          </section>
        </section>
      )}

      {notice && (
        <p className="feedback feedback-success" role="status">
          {notice}
        </p>
      )}
      {error && (
        <p className="feedback feedback-error" role="alert">
          {error}
        </p>
      )}

      <p className="scope-note">
        A single fixed webcam monitors only its visible room and field of view.
        Camera movement pauses alerts. Image zones are approximate; ordinary
        webcam images cannot provide reliable physical distance or guarantee
        that a walkway is safe.
      </p>
    </main>
  );
}

export default App;
