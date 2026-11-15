import { objectLabel, formatDate } from "../../utils/formatters.js";

/**
 * LiveObjects – "Live Objects" monitoring tab panel.
 *
 * Props:
 *   isActive         boolean    – true when this tab is selected (controls visibility class)
 *   latest           object     – latest scan result { detections[], captured_at }
 *   knownObjectNames Set<string> – class names from the baseline (to flag new objects)
 *   cameraActive     boolean    – whether the camera is currently running
 */
export default function LiveObjects({ isActive, latest, knownObjectNames, cameraActive }) {
  return (
    <div
      id="tab-panel-monitor"
      role="tabpanel"
      className={`tab-panel ${!isActive ? "tab-panel-hidden" : ""}`}
      aria-label="Live detected objects"
    >
      <div className="panel">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">LIVE OBSERVATIONS</p>
            <h2>Latest detected objects</h2>
          </div>
          {cameraActive && <span className="saved-badge">Live scan</span>}
        </div>
        {latest?.detections?.length ? (
          <ul className="object-list latest-list" aria-label="Currently detected objects">
            {latest.detections.map((object, index) => {
              const isOutsideBaseline = !knownObjectNames.has(object.class_name) && cameraActive;
              return (
                <li
                  className={`object-card ${isOutsideBaseline ? "object-card-new" : ""}`}
                  key={`${object.class_name}-${object.instance_number}-${index}`}
                  aria-label={`${object.class_name}${isOutsideBaseline ? " — not in original layout" : ""}, zone: ${object.zone}`}
                >
                  <span className="object-symbol" aria-hidden="true">
                    {object.class_name.slice(0, 1).toUpperCase()}
                  </span>
                  <span className="object-description">
                    <strong>{objectLabel(object)}{isOutsideBaseline ? " · New" : ""}</strong>
                    <span>{object.zone} | {Math.round(object.confidence * 100)}% confidence</span>
                  </span>
                </li>
              );
            })}
          </ul>
        ) : (
          <p className="history-empty">
            {latest
              ? "No supported objects visible in the latest scan."
              : "Start monitoring to show the latest reliable camera observations."}
          </p>
        )}
        {latest?.captured_at && (
          <p className="saved-meta">Last reliable scan: {formatDate(latest.captured_at)}</p>
        )}
      </div>
    </div>
  );
}
