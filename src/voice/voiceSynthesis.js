/**
 * voiceSynthesis.js – Pure browser speech synthesis helpers.
 *
 * No React state dependencies. Wraps the Web Speech API (SpeechSynthesis)
 * so callers don't need to repeat capability checks or construct utterances
 * manually throughout the codebase.
 *
 * All functions are safe to call even when the API is unavailable — they
 * check support internally and do nothing if the browser cannot comply.
 */

/**
 * Returns true when the browser supports speech synthesis.
 * Checks both the speechSynthesis global and the SpeechSynthesisUtterance
 * constructor, matching the guards used in the original App.jsx.
 *
 * @returns {boolean}
 */
export function isSpeechSynthesisSupported() {
  return (
    "speechSynthesis" in window &&
    typeof window.SpeechSynthesisUtterance === "function"
  );
}

/**
 * Unlocks the Web Speech API on user gesture so subsequent speech calls
 * are permitted under browser audio autoplay policies.
 *
 * @returns {boolean} True if unlock attempt succeeded or was initiated.
 */
export function unlockSpeechSynthesis() {
  if (!isSpeechSynthesisSupported()) return false;
  try {
    window.speechSynthesis.cancel();
    const utterance = new window.SpeechSynthesisUtterance("");
    utterance.volume = 0.01;
    window.speechSynthesis.speak(utterance);
    return true;
  } catch {
    return false;
  }
}

/**
 * Speaks the given text using the browser's speech synthesis engine.
 *
 * Does nothing if synthesis is unsupported.
 *
 * @param {string} text                    - The text to speak.
 * @param {object} [options]
 * @param {number} [options.rate=0.92]     - Speech rate (0.1–10). Default is 0.92 for clarity.
 * @param {number} [options.volume=1]      - Speech volume (0–1).
 * @param {boolean} [options.interrupt=true] - If true, cancels active speech before speaking.
 * @param {Function} [options.onEnd]       - Called when the utterance finishes successfully.
 * @param {Function} [options.onError]     - Called with the SpeechSynthesisErrorEvent on failure.
 */
export function speakText(
  text,
  { rate = 0.92, volume = 1, interrupt = true, onEnd, onError } = {},
) {
  if (!isSpeechSynthesisSupported() || !text || !text.trim()) return;
  try {
    if (interrupt && "speechSynthesis" in window) {
      window.speechSynthesis.cancel();
    }
    const utterance = new window.SpeechSynthesisUtterance(text.trim());
    if (rate !== undefined) utterance.rate = rate;
    if (volume !== undefined) utterance.volume = volume;
    if (onEnd) utterance.onend = onEnd;
    if (onError) utterance.onerror = onError;
    window.speechSynthesis.speak(utterance);
  } catch (error) {
    if (onError) {
      onError({ error: error.message || "Speech synthesis exception" });
    }
  }
}

/**
 * Cancels any currently playing or queued speech.
 * Safe to call even when synthesis is unsupported.
 */
export function cancelSpeech() {
  if ("speechSynthesis" in window) {
    try {
      window.speechSynthesis.cancel();
    } catch {
      // Ignored
    }
  }
}

/**
 * Formats a clean spoken announcement for live monitoring change events.
 *
 * @param {object} alert
 * @returns {string}
 */
export function formatAlertAnnouncement(alert) {
  if (!alert) return "";
  const name = alert.class_name || alert.object_name || "object";
  const changeType = alert.change_type;
  if (changeType === "camera_view_changed") {
    return "Warning! The camera has moved. Monitoring is temporarily paused.";
  }
  if (changeType === "camera_view_unverified") {
    return "Warning! The camera view cannot be verified. Monitoring is paused.";
  }
  if (changeType === "camera_view_restored") {
    return "The saved camera view is restored. Room monitoring has resumed.";
  }
  if (changeType === "object_moved" || changeType === "moved") {
    return `Warning! The ${name} has moved from its previous position.`;
  }
  if (
    changeType === "object_missing" ||
    changeType === "missing" ||
    changeType === "not_currently_visible"
  ) {
    return `Warning! The ${name} is missing from its previous position.`;
  }
  if (
    changeType === "object_appeared" ||
    changeType === "new" ||
    changeType === "newly_visible"
  ) {
    return `Warning! A new ${name} has appeared in the room.`;
  }
  return alert.message || `Change detected for ${name}.`;
}

/**
 * Formats a clean spoken announcement for Before and After comparison results.
 *
 * @param {object} comparison
 * @param {string} [effectiveRoomName="room"]
 * @returns {string}
 */
export function formatComparisonAnnouncement(comparison, effectiveRoomName = "room") {
  if (!comparison) return "";
  const room = (effectiveRoomName && typeof effectiveRoomName === "string" ? effectiveRoomName.trim() : "room") || "room";

  if (comparison.status === "error") {
    return `Comparison failed: ${comparison.error || "Unexpected error."}`;
  }

  const diff = comparison.comparison;
  const moved = diff?.moved || [];
  const missing = diff?.missing || diff?.not_currently_visible || [];
  const newlyVisible = diff?.new || diff?.newly_visible || [];
  const totalChanges = moved.length + missing.length + newlyVisible.length;

  if (comparison.status === "uncertain") {
    if (totalChanges > 0) {
      const suspectName = missing[0]?.class_name || newlyVisible[0]?.class_name || moved[0]?.class_name || "object";
      return `Possible room change detected. One ${suspectName} may be missing, but camera alignment could not be confirmed. Please align the camera and try again.`;
    }
    return "Possible room change detected. One object may be missing, but camera alignment could not be confirmed. Please align the camera and try again.";
  }

  if (totalChanges === 0 && comparison.status === "unchanged") {
    return "No significant room changes detected.";
  }

  const parts = [];
  parts.push("Room change detected.");

  for (const item of missing) {
    const name = item.class_name || item.object_name || "object";
    parts.push(`One ${name} is missing from the ${room}.`);
  }
  for (const item of newlyVisible) {
    const name = item.class_name || item.object_name || "object";
    parts.push(`A new ${name} is present in the ${room}.`);
  }
  for (const item of moved) {
    const name = item.class_name || item.object_name || "object";
    parts.push(`The ${name} has moved from its previous position.`);
  }

  return parts.join(" ");
}
