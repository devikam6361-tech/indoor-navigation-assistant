// RoomSelector — lets the user pick a preset room, enter a custom name,
// or jump to any room that already has a saved baseline.
//
// Props (all required):
//   presetRooms      string[]   — list of preset room name strings
//   roomName         string     — currently selected preset room
//   isCustomRoom     bool       — whether custom-room mode is active
//   customRoomName   string     — current custom name input value
//   knownRooms       object[]   — rooms with saved baselines [{room_key, room_name, detection_count}]
//   cameraActive     bool       — if true, camera is stopped before switching room
//   onPresetSelect   fn(room)   — called when a preset pill is clicked
//   onCustomToggle   fn()       — called when the "Custom" pill is clicked
//   onCustomNameChange fn(name) — called on every keystroke in the custom-name input
//   onKnownRoomSelect fn(r)     — called when a known-room link button is clicked
export default function RoomSelector({
  presetRooms,
  roomName,
  isCustomRoom,
  customRoomName,
  knownRooms,
  onPresetSelect,
  onCustomToggle,
  onCustomNameChange,
  onKnownRoomSelect,
}) {
  return (
    <section className="room-selector-section" aria-label="Room selection">
      <div className="room-selector-card">
        <h2 className="room-selector-heading">
          <span aria-hidden="true">🏠</span> Select Room
        </h2>

        <div className="room-pills" role="group" aria-label="Preset rooms">
          {presetRooms.map((room) => (
            <button
              key={room}
              className={`room-pill ${!isCustomRoom && roomName === room ? "room-pill-active" : ""}`}
              onClick={() => onPresetSelect(room)}
              aria-pressed={!isCustomRoom && roomName === room}
              aria-label={`Select ${room}`}
            >
              {room}
            </button>
          ))}
          <button
            className={`room-pill ${isCustomRoom ? "room-pill-active" : ""}`}
            onClick={onCustomToggle}
            aria-pressed={isCustomRoom}
            aria-label="Enter custom room name"
          >
            Custom
          </button>
        </div>

        {isCustomRoom && (
          <label className="room-field custom-room-field">
            <span>Custom room name</span>
            <input
              aria-label="Enter custom room name"
              maxLength={80}
              onChange={(e) => {
                const next = e.target.value;
                if (next !== customRoomName) onCustomNameChange(next);
              }}
              placeholder="e.g. Study, Garage..."
              value={customRoomName}
              autoFocus
            />
          </label>
        )}

        {knownRooms.length > 0 && (
          <p className="known-rooms-note" aria-live="polite">
            Rooms with saved layouts:{" "}
            {knownRooms.map((r) => (
              <button
                key={r.room_key}
                className="known-room-link"
                onClick={() => onKnownRoomSelect(r)}
                aria-label={`Switch to ${r.room_name} (${r.detection_count} objects)`}
              >
                {r.room_name} ({r.detection_count})
              </button>
            ))}
          </p>
        )}
      </div>
    </section>
  );
}
