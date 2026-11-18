import { render, screen, fireEvent, cleanup } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import ComparisonModal from "./components/monitoring/ComparisonModal.jsx";

const FAKE_BEFORE_IMAGE = "data:image/jpeg;base64,/9j/4AAQSkZJRg==";
const FAKE_AFTER_IMAGE = "data:image/jpeg;base64,/9j/4AAQSkZJRg==";

afterEach(() => {
  cleanup();
});

describe("ComparisonModal", () => {
  it("displays actual BEFORE and AFTER images side by side with detection cards", () => {
    const comparisonData = {
      status: "unchanged",
      before: {
        id: 1,
        image_data_url: FAKE_BEFORE_IMAGE,
        detections: [
          { class_name: "chair", confidence: 0.92, x1: 0.1, y1: 0.1, x2: 0.3, y2: 0.4 },
        ],
      },
      after: {
        id: 2,
        image_data_url: FAKE_AFTER_IMAGE,
        detections: [
          { class_name: "chair", confidence: 0.91, x1: 0.1, y1: 0.1, x2: 0.3, y2: 0.4 },
        ],
      },
      comparison: {
        summary: { unchanged: 1, moved: 0, new: 0, missing: 0, total_baseline: 1, total_latest: 1 },
        unchanged: [{ class_name: "chair", zone: "center" }],
        moved: [],
        new: [],
        missing: [],
      },
    };

    render(
      <ComparisonModal
        comparison={comparisonData}
        effectiveRoomName="Living room"
        onClose={vi.fn()}
      />
    );

    // Both layouts are rendered
    expect(screen.getByText(/BEFORE — Original arrangement/)).toBeTruthy();
    expect(screen.getByText(/AFTER — Updated arrangement/)).toBeTruthy();

    // No changes detected banner is displayed
    expect(
      screen.getByText("No significant changes detected between BEFORE and AFTER.")
    ).toBeTruthy();
  });

  it("identifies and displays detailed change alerts for missing, moved, and new objects", () => {
    const comparisonData = {
      status: "changed",
      before: {
        id: 1,
        image_data_url: FAKE_BEFORE_IMAGE,
        detections: [
          { class_name: "bin", confidence: 0.88, x1: 0.1, y1: 0.2, x2: 0.25, y2: 0.5 },
          { class_name: "chair", confidence: 0.93, x1: 0.3, y1: 0.3, x2: 0.5, y2: 0.7 },
        ],
      },
      after: {
        id: 2,
        image_data_url: FAKE_AFTER_IMAGE,
        detections: [
          { class_name: "chair", confidence: 0.90, x1: 0.6, y1: 0.3, x2: 0.8, y2: 0.7 },
          { class_name: "backpack", confidence: 0.85, x1: 0.1, y1: 0.6, x2: 0.3, y2: 0.9 },
        ],
      },
      comparison: {
        summary: { unchanged: 0, moved: 1, new: 1, missing: 1, total_baseline: 2, total_latest: 2 },
        unchanged: [],
        missing: [
          { class_name: "bin", zone: "left" },
        ],
        moved: [
          {
            class_name: "chair",
            original_zone: "center",
            current_zone: "right",
            previous_position: { zone: "center" },
            current_position: { zone: "right" },
          },
        ],
        new: [
          { class_name: "backpack", current_zone: "bottom-left", zone: "bottom-left" },
        ],
      },
    };

    render(
      <ComparisonModal
        comparison={comparisonData}
        effectiveRoomName="Living room"
        onClose={vi.fn()}
      />
    );

    // Header banner indicates changes detected
    expect(
      screen.getByText(/CHANGE DETECTED: Room Arrangement Modified/)
    ).toBeTruthy();

    // Missing object card & message
    expect(screen.getByText("MISSING")).toBeTruthy();
    expect(
      screen.getByText(
        "CHANGE DETECTED: The bin was present in the BEFORE image but is missing in the AFTER image."
      )
    ).toBeTruthy();

    // Moved object card & message
    expect(screen.getByText("MOVED")).toBeTruthy();
    expect(
      screen.getByText("CHANGE DETECTED: The chair has moved from its previous position.")
    ).toBeTruthy();
    expect(screen.getByText("center")).toBeTruthy();
    expect(screen.getByText("right")).toBeTruthy();

    // New object card & message
    expect(screen.getByText("NEW OBJECT")).toBeTruthy();
    expect(
      screen.getByText(
        "CHANGE DETECTED: A new object (backpack) has appeared in the room."
      )
    ).toBeTruthy();
  });

  it("calls onReplayVoice when Replay Voice button is clicked", () => {
    const onReplayVoice = vi.fn();
    const comparisonData = {
      status: "changed",
      before: { id: 1, image_data_url: FAKE_BEFORE_IMAGE, detections: [] },
      after: { id: 2, image_data_url: FAKE_AFTER_IMAGE, detections: [] },
      comparison: {
        summary: { unchanged: 0, moved: 1, new: 0, missing: 0, total_baseline: 1, total_latest: 1 },
        unchanged: [],
        missing: [],
        moved: [{ class_name: "chair", original_zone: "left", current_zone: "right" }],
        new: [],
      },
    };

    // Mock speechSynthesis
    Object.defineProperty(window, "speechSynthesis", {
      configurable: true,
      value: { speak: vi.fn(), cancel: vi.fn() },
    });
    window.SpeechSynthesisUtterance = vi.fn();

    render(
      <ComparisonModal
        comparison={comparisonData}
        effectiveRoomName="Living room"
        onReplayVoice={onReplayVoice}
        onClose={vi.fn()}
      />
    );

    const replayBtn = screen.getByRole("button", { name: "Replay voice announcement" });
    fireEvent.click(replayBtn);

    expect(onReplayVoice).toHaveBeenCalledTimes(1);
    expect(onReplayVoice.mock.calls[0][0]).toContain("The chair has moved from its previous position.");
  });

  it("displays explicit error message on comparison failure and never treats it as unchanged", () => {
    const comparisonData = {
      status: "error",
      error: "Camera moved significantly during comparison.",
      before: null,
      after: null,
    };

    render(
      <ComparisonModal
        comparison={comparisonData}
        effectiveRoomName="Living room"
        onClose={vi.fn()}
      />
    );

    expect(screen.getByText("Comparison Failed")).toBeTruthy();
    expect(
      screen.getByText("Camera moved significantly during comparison.")
    ).toBeTruthy();
    // Must NOT say "no changes detected"
    expect(
      screen.queryByText("No significant changes detected between BEFORE and AFTER.")
    ).toBeNull();
  });
});
