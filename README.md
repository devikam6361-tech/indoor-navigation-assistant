# Indoor Home Layout Assistant

The prototype learns one original room layout from a fixed webcam view, then
periodically compares reliable new observations with that saved baseline.
React captures webcam frames; the local Flask API uses the bundled Ultralytics
YOLO model and OpenCV; SQLite stores the original room image and detections,
latest reliable observation, monitor state, and alert history.

## Requirements

- Windows laptop with Python 3.10 or later
- Node.js and npm
- Webcam access in the browser
- The bundled `yolo11n.pt` model file

## Run locally

In one PowerShell window, from this project directory:

```powershell
python -m pip install -r requirements.txt
python -m ai.server
```

In another PowerShell window, from this project directory:

```powershell
npm install
npm run dev
```

Open the local Vite URL printed in the second window (usually
`http://localhost:5173`). Allow camera access and enter a room name. For a room
without a baseline, select **Learn Home Layout** to save its image and actual
YOLO detections. Review the saved image and supported object list. For an
existing baseline, use **Relearn room** only when you intentionally want to
replace it; ordinary scans never overwrite the baseline.

Select **Start monitoring** with the camera in the same fixed position. The
page submits a frame every 2.5 seconds while monitoring. A move, new object, or
not-currently-visible status must be observed in three consecutive reliable
scans before an alert is recorded and automatically spoken. The alert history
shows the message, object, time, detection confidence, and voice playback
status. **Repeat report** speaks recent history. **Find an object** and
**Ask by voice** use the latest reliable scan, or clearly identify when they
can only use the original baseline.

If the baseline contains zero supported object detections, opening the camera
does not start change monitoring. Reframe the camera on visible household
objects and explicitly relearn the room first, so the system does not treat
the entire room as newly appeared furniture.

The Flask API is available at `http://127.0.0.1:5000`; Vite proxies `/api`
requests to it. SQLite data is stored locally at
`ai/instance/home_layout.sqlite3`.

## Change detection and safety limits

- One webcam monitors only its visible field of view; it cannot monitor unseen
  rooms.
- Keep the same camera viewpoint. OpenCV feature matching checks the current
  view against the baseline. A detected camera shift pauses alerts; if the
  view cannot be verified, changes are not announced.
- Changes are compared by YOLO class and approximate normalized image
  positions. Objects of the same class are matched by nearest position.
  YOLO does not provide persistent identities, so identity matching between
  similar objects is approximate.
- A missing detection is announced only as **not currently visible**; it does
  not establish that the object was removed.
- A new supported furniture-like object in the lower-center image zone may
  receive a cautious possible-obstacle warning. The camera cannot establish
  that a walkway is actually blocked.
- Image zones are approximate and do not provide physical distance. This
  prototype cannot guarantee safe navigation; do not rely on it alone.
- YOLO can miss small, occluded, or unsupported objects. It uses COCO labels;
  for example, keys and shoes may not be recognized.
- Voice alerts use the browser's speech synthesis. Browser/device voice
  playback failure is displayed and retained in alert history. Voice search
  depends on browser speech-recognition support and permission.

## Verification

From this directory:

```powershell
python -m unittest discover -s ai -p "test_*.py" -v
python -m py_compile ai\server.py ai\test_server.py
npm run lint
npm run build
```

The API tests use deterministic mocked model outputs to verify baseline storage,
three-scan confirmation, cooldown/deduplication, temporary occlusion,
not-currently-visible wording, cautious obstacle alerts, camera movement,
lighting tolerance, object finding, and voice playback failure handling. The
running application uses real YOLO inference.

## Manual end-to-end test

1. Run Flask and Vite as described above; allow browser camera and microphone
   access if using voice search.
2. Point the fixed camera at a well-lit room with one or more supported objects
   and select **Learn Home Layout**. Confirm that the saved image and detections
   reflect the real room.
3. Select **Start monitoring** and leave the camera fixed. Move a visible chair
   or bottle to a different image zone. After three matching scans, expect one
   spoken, time-stamped movement alert.
4. Place a supported chair or bag in the lower-center of view. After
   confirmation, expect a cautious possible-obstacle alert, not a claim that
   the walking path is blocked.
5. Temporarily cover an object for one or two scans and uncover it. No missing
   alert should appear. If it stays absent for three reliable scans, the alert
   must say it is **not currently visible**, not that it was removed.
6. Change room lighting without moving the webcam. The view check should
   tolerate ordinary lighting variation. Move or rotate the camera instead;
   monitoring should pause and say the view changed or could not be verified.
7. Select **Repeat report** or use **Find an object** / **Ask by voice**. A
   current finding refers to the latest reliable scan; a baseline-only finding
   explicitly says it is not a current sighting.
8. Inspect the alert history for voice status. Deny or disable browser speech
   output to confirm playback failure/unavailability is reported instead of
   silently marked as spoken.
