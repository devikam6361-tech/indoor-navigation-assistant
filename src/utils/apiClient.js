// Thin wrapper around fetch that guards against non-JSON error pages.
// Throws with the server's error message so callers can display it directly.

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
