# AI-Powered Indoor Room Change Detection and Voice Alert System

Helps blind users monitor their home using a laptop webcam, YOLO object
detection, and automatic voice alerts. Each room has its own saved baseline;
the system periodically compares live camera frames with that baseline and
announces confirmed changes by voice.

---

## Technology Stack

| Layer | Technology |
|-------|-----------|
| Frontend | React 19, Vite 8 |
| Backend | Python Flask 3, SQLite |
| Object detection | Ultralytics YOLO 11n (COCO labels) |
| Image processing | OpenCV 4 |
| Voice alerts | Web Speech API (browser-native) |
| Camera | Laptop webcam via `getUserMedia` |

---

## Features

| # | Feature | Status |
|---|---------|--------|
| 1 | Multiple room management (Bedroom, Kitchen, Living room, Bathroom, Other, Custom) | ✅ |
| 2 | Capture Original Layout — webcam → YOLO → SQLite baseline | ✅ |
| 3 | Automatic room monitoring every 2.5 s | ✅ |
| 4 | Before-and-after side-by-side image comparison with bounding boxes | ✅ |
| 5 | Automatic voice alerts (moved, new object, not visible) | ✅ |
| 6 | Voice-based object finding ("Where is my bag?") | ✅ |
| 7 | Persistent change history per room in SQLite | ✅ |
| 8 | Accessible UI — ARIA labels, keyboard nav, high-contrast, reduced-motion | ✅ |
| 9 | REST API — `/api/baseline`, `/api/observe`, `/api/rooms`, `/api/comparison`, `/api/find`, `/api/alerts` | ✅ |
| 10 | 26 automated tests — all passing | ✅ |

---

## Requirements

- **Python 3.10 or later** (tested on 3.12)
- **Node.js 18 or later** and npm
- Browser camera and microphone access (Chrome or Edge recommended)
- The bundled `yolo11n.pt` YOLO model file (already in the project)

---

## Quick Start

### 1 — Backend (Flask + YOLO)

Open a PowerShell window in the project directory:

```powershell
pip install -r requirements.txt
python -m ai.server
```

The Flask API starts at `http://127.0.0.1:5000`.

### 2 — Frontend (React + Vite)

Open a second PowerShell window in the same directory:

```powershell
npm install
npm run dev
```

Open the URL printed by Vite (usually `http://localhost:5173`).

---

## How to Use

### Capture a Room Baseline

1. Select a preset room (Bedroom, Kitchen, Living room, Bathroom, Other) or
   choose **Custom** and type your own name.
2. Click **▶ Start Webcam** (the button is enabled after a room is selected).
   Allow camera access in the browser prompt.
3. Point the camera at the area you want to monitor and keep it fixed.
4. Click **📷 Capture Original Layout**.
   - YOLO detects and saves supported objects (chair, bottle, bag, couch, etc.).
   - The saved image and object list appear in the **Original Layout** panel.
5. Click **▶ Start Monitoring** to begin periodic change detection.

### Monitor for Changes

- The app submits a camera frame every 2.5 seconds.
- A change must appear in **three consecutive reliable scans** before an alert
  fires. This prevents false positives from brief occlusions.
- Alerts are announced by voice and stored in the **Alert History** tab.
- A 60-second cooldown prevents the same alert from repeating.

### Compare Before and After

- After at least one monitoring scan, the **🔍 View Before & After Comparison**
  button appears below the camera.
- This opens a modal showing the original layout and the latest scan side by
  side, each with YOLO bounding boxes drawn over detected objects.

### Find an Object by Voice or Text

- Switch to the **🔎 Find Object** tab.
- Type an object name (e.g., "bag", "bottle", "chair") or click **🎤 Ask by
  voice** and speak a question like *"Where is my bag?"*.
- The system checks the latest reliable scan first, then falls back to the
  baseline if monitoring has not started yet.

### Room Isolation

Each room has its own baseline and change history. Changes detected in one room
are never reported for another. After saving a layout for a room, its name
appears in the **Rooms with saved layouts** list for quick switching.

---

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/health` | Service health check |
| `GET` | `/api/rooms` | List all rooms with a saved baseline |
| `GET` | `/api/baseline?room_name=` | Fetch the saved baseline for a room |
| `POST` | `/api/baseline` | Save or replace a room baseline |
| `GET` | `/api/latest?room_name=` | Fetch the latest reliable observation |
| `GET` | `/api/comparison?room_name=` | Fetch baseline + latest for side-by-side comparison |
| `POST` | `/api/observe` | Submit a new camera frame for analysis |
| `GET` | `/api/alerts?room_name=` | Fetch alert history for a room |
| `POST` | `/api/alerts/<id>/playback` | Record voice-playback result |
| `GET` | `/api/find?room_name=&object_name=` | Find an object in the latest scan |

All endpoints accept and return JSON. Images are sent as base64-encoded JPEG
data URLs.

---

## Change Detection Logic

1. **Camera view verification** — OpenCV ORB feature matching checks whether
   the camera has moved relative to the baseline. A confirmed move or
   unverifiable view suspends object alerts.
2. **Object matching** — YOLO detections are matched across frames by class
   name and nearest normalized centre position.
3. **Three-frame confirmation** — a candidate change must appear in three
   consecutive stable-view scans before an alert is recorded.
4. **Cooldown** — the same change signature is suppressed for 60 seconds after
   its first alert.
5. **Wording safety** — a missing detection is reported as *"not currently
   visible"*, not *"removed"*. A large object in the lower-centre zone triggers
   a cautious possible-obstacle warning, not a claim that the path is blocked.

---

## Supported YOLO Object Classes

backpack · bed · bottle · bowl · book · chair · clock · couch · cup ·
dining table · hair drier · handbag · keyboard · laptop · microwave ·
mouse · oven · potted plant · refrigerator · remote · scissors · sink ·
suitcase · toaster · toothbrush · tv · vase

---

## Running Tests

```powershell
# From the project directory
python -m unittest discover -s ai -p "test_*.py" -v
```

**Expected result: 26 tests, all OK.**

Tests cover:
- Baseline capture, replacement, and persistence across restarts
- Three-scan change confirmation for moved, new, and missing objects
- Cooldown / deduplication logic
- Temporary occlusion (must not trigger a "missing" alert)
- Camera movement — alerts must pause; restored view must be announced
- Cautious obstacle wording for furniture in the lower-centre zone
- Object finder with aliases and camera-moved suppression
- Voice-playback failure recording
- `GET /api/rooms` — empty list, multiple rooms, replaced baseline
- `GET /api/comparison` — baseline + latest, null latest before monitoring
- Room isolation — changes in one room must not appear in another

---

## Manual End-to-End Test

1. Run Flask and Vite as above. Allow browser camera and microphone access.
2. Select **Bedroom** and click **▶ Start Webcam**.
3. Point the camera at a chair in the bedroom and click **📷 Capture Original
   Layout**. Confirm the chair appears in the object list.
4. Click **▶ Start Monitoring**. Move the chair to a different position.
   After three matching scans (~7 s), expect one spoken alert:
   *"A chair appears to have moved from … to … in the camera view."*
5. Select **Kitchen** and repeat with a bottle. Confirm that bedroom alerts
   do not appear in the kitchen history.
6. Move the chair back; no new alert should fire within the 60-second cooldown.
7. Click **🔍 View Before & After Comparison**. Both images should show
   bounding boxes; the chair should be in different positions.
8. Switch to **🔎 Find Object**, type *bottle*, and click **🔎 Find object**.
   Expect a location description spoken aloud.
9. Click **🎤 Ask by voice** and say *"Where is my chair?"*. Expect a voice
   response about the current or last-known position.
10. Restart the browser tab. Reload; saved baselines and history must persist.

---

## Data Storage

SQLite database: `ai/instance/home_layout.sqlite3`

| Table | Contents |
|-------|----------|
| `observations` | Baseline images and metadata per room |
| `detections` | YOLO detections for each observation |
| `latest_observations` | Most recent reliable frame per room |
| `change_events` | Confirmed change alerts with voice-playback status |
| `room_monitor_status` | Current camera-view status per room |

---

## Known Limitations

- One webcam monitors only its visible field of view. Move the camera and alerts
  pause automatically.
- YOLO uses COCO labels. Keys, shoes, and other small objects may not be
  recognized.
- Zones (upper-left, lower-center, etc.) are approximate image regions, not
  physical distances.
- Voice alerts use the browser's built-in speech synthesis. Quality and
  availability vary by browser and operating system.
- This prototype cannot guarantee safe navigation. Do not rely on it alone.
