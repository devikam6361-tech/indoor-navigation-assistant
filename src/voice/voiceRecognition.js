/**
 * voiceRecognition.js – Pure browser speech recognition helpers.
 *
 * No React state dependencies. Wraps the Web Speech API (SpeechRecognition)
 * so callers don't need to repeat capability checks or repeat the same
 * recognition configuration throughout the codebase.
 *
 * All functions are safe to call even when the API is unavailable — callers
 * should check isSpeechRecognitionSupported() before calling createRecognition().
 */

/**
 * Returns true when the browser exposes a SpeechRecognition constructor
 * (standard or webkit-prefixed). Matches the guard used in startVoiceSearch.
 *
 * @returns {boolean}
 */
export function isSpeechRecognitionSupported() {
  return !!(window.SpeechRecognition || window.webkitSpeechRecognition);
}

/**
 * Creates and returns a configured SpeechRecognition instance.
 *
 * Settings match the original App.jsx implementation:
 *   - continuous: false   – single-utterance capture
 *   - interimResults: false – final transcript only
 *
 * @param {string} [lang="en-US"] – BCP-47 language tag for recognition.
 * @returns {SpeechRecognition}
 */
export function createRecognition(lang = "en-US") {
  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  const recognition = new SpeechRecognition();
  recognition.lang = lang;
  recognition.continuous = false;
  recognition.interimResults = false;
  return recognition;
}
