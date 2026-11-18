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

// ===============================
// VIDEO UPLOAD AND FRAME EXTRACTION
// ===============================

// Upload multiple videos for processing and frame extraction
export async function uploadVideos(videoFiles) {
  const formData = new FormData();

  videoFiles.forEach((file) => {
    formData.append("videos", file);
  });

  const response = await fetch("/api/videos/upload", {
    method: "POST",
    body: formData,
  });

  return readJson(response);
}

// Get all uploaded videos and their extracted frame information
export async function fetchVideos() {
  const response = await fetch("/api/videos");
  return readJson(response);
}

// Generate the URL for an extracted frame
export function getVideoFrameUrl(videoId, filename) {
  return `/api/videos/${encodeURIComponent(
    videoId
  )}/frames/${encodeURIComponent(filename)}`;
}

// Generate the URL for the raw uploaded video source
export function getVideoSourceUrl(videoId) {
  return `/api/videos/${encodeURIComponent(videoId)}/source`;
}

// Compare two video frames to detect room changes
export async function compareVideos({
  beforeVideoId,
  afterVideoId,
  beforeFrame = "frame_0000.jpg",
  afterFrame = "frame_0000.jpg",
}) {
  const response = await fetch("/api/videos/compare", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      before_video_id: beforeVideoId,
      after_video_id: afterVideoId,
      before_frame: beforeFrame,
      after_frame: afterFrame,
    }),
  });
  return readJson(response);
}
