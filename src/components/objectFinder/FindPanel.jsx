/**
 * FindPanel – "Find an Object" tab panel (voice-assisted finder).
 *
 * Props:
 *   isActive        boolean   – true when this tab is selected (controls visibility class)
 *   findQuery       string    – current text input value
 *   setFindQuery    fn        – state setter from App
 *   findResult      string    – result text to display (empty string = no result yet)
 *   onFind          () => void – submits the text search (calls findObject in App)
 *   onVoiceSearch   () => void – starts voice recognition search (calls startVoiceSearch in App)
 */
export default function FindPanel({
  isActive,
  findQuery,
  setFindQuery,
  findResult,
  onFind,
  onVoiceSearch,
}) {
  return (
    <div
      id="tab-panel-find"
      role="tabpanel"
      className={`tab-panel ${!isActive ? "tab-panel-hidden" : ""}`}
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
          onSubmit={(event) => { event.preventDefault(); onFind(); }}
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
            onClick={onVoiceSearch}
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
  );
}
