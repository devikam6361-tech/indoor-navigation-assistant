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
 * Speaks the given text using the browser's speech synthesis engine.
 *
 * Does nothing if synthesis is unsupported.
 *
 * @param {string} text        - The text to speak.
 * @param {object} [options]
 * @param {number} [options.rate=1]       - Speech rate (0.1–10). Default is browser default.
 * @param {Function} [options.onEnd]      - Called when the utterance finishes successfully.
 * @param {Function} [options.onError]    - Called with the SpeechSynthesisErrorEvent on failure.
 */
export function speakText(text, { rate, onEnd, onError } = {}) {
  if (!isSpeechSynthesisSupported()) return;
  const utterance = new window.SpeechSynthesisUtterance(text);
  if (rate !== undefined) utterance.rate = rate;
  if (onEnd) utterance.onend = onEnd;
  if (onError) utterance.onerror = onError;
  window.speechSynthesis.speak(utterance);
}

/**
 * Cancels any currently playing or queued speech.
 * Safe to call even when synthesis is unsupported.
 */
export function cancelSpeech() {
  if ("speechSynthesis" in window) {
    window.speechSynthesis.cancel();
  }
}
