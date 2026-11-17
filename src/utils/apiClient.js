// Thin wrapper around fetch that guards against non-JSON error pages.
// Throws with the server's error message so callers can display it directly.

export const DEFAULT_CAMERA_ID = "default-webcam";

export async function readJson(response) {
  const contentType = response.headers.get("content-type") || "";
  if (!contentType.includes("application/json")) {
    throw new Error(
      `Server error ${response.status} — check Flask is running at http://127.0.0.1:5000`,
    );
  }
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.error || `Request failed (${response.status})`);
  }
  return payload;
}

export async function fetchLayouts(roomName, cameraId, options = {}) {
  const query = new URLSearchParams({
    room_name: roomName,
    camera_id: cameraId,
  });
  return readJson(await fetch(`/api/layouts?${query}`, { signal: options.signal }));
}

export async function createLayout({
  roomName,
  cameraId,
  layoutName,
  image,
  activate = true,
}) {
  return readJson(
    await fetch("/api/layouts", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        room_name: roomName,
        camera_id: cameraId,
        layout_name: layoutName,
        image,
        activate,
      }),
    }),
  );
}

export async function compareLayouts({
  roomName,
  cameraId,
  beforeLayoutId,
  afterLayoutId,
}) {
  return readJson(
    await fetch("/api/layouts/compare", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        room_name: roomName,
        camera_id: cameraId,
        before_layout_id: beforeLayoutId,
        after_layout_id: afterLayoutId,
      }),
    }),
  );
}

export async function activateLayout(layoutId, roomName, cameraId) {
  return readJson(
    await fetch(`/api/layouts/${encodeURIComponent(layoutId)}/activate`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ room_name: roomName, camera_id: cameraId }),
    }),
  );
}

export async function deleteLayout(layoutId, roomName, cameraId) {
  const query = new URLSearchParams({
    room_name: roomName,
    camera_id: cameraId,
  });
  return readJson(
    await fetch(`/api/layouts/${encodeURIComponent(layoutId)}?${query}`, {
      method: "DELETE",
    }),
  );
}