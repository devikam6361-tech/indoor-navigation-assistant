import { render, screen, fireEvent, cleanup } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import CameraPanel from "./components/camera/CameraPanel.jsx";
import LiveObjects from "./components/monitoring/LiveObjects.jsx";
import {
  formatComparisonAnnouncement,
  formatAlertAnnouncement,
} from "./voice/voiceSynthesis.js";

afterEach(() => {
  cleanup();
});

describe("Problem 1: Voice Announcement Generation", () => {
  it("generates confirmed missing object announcement with room name", () => {
    const comparison = {
      status: "changed",
      comparison: {
        missing: [{ class_name: "bottle" }],
        new: [],
        moved: [],
        unchanged: [],
      },
    };
    const announcement = formatComparisonAnnouncement(comparison, "Bedroom");
    expect(announcement).toContain("Room change detected.");
    expect(announcement).toContain("One bottle is missing from the Bedroom.");
  });

  it("generates confirmed new object announcement with room name", () => {
    const comparison = {
      status: "changed",
      comparison: {
        missing: [],
        new: [{ class_name: "notebook" }],
        moved: [],
        unchanged: [],
      },
    };
    const announcement = formatComparisonAnnouncement(comparison, "Bedroom");
    expect(announcement).toContain("Room change detected.");
    expect(announcement).toContain("A new notebook is present in the Bedroom.");
  });

  it("generates confirmed moved object announcement", () => {
    const comparison = {
      status: "changed",
      comparison: {
        missing: [],
        new: [],
        moved: [{ class_name: "chair" }],
        unchanged: [],
      },
    };
    const announcement = formatComparisonAnnouncement(comparison, "Living room");
    expect(announcement).toContain("The chair has moved from its previous position.");
  });

  it("generates clear inconclusive announcement when camera viewpoint is uncertain", () => {
    const comparison = {
      status: "uncertain",
      comparison: {
        missing: [{ class_name: "bottle" }],
        new: [],
        moved: [],
        unchanged: [],
      },
    };
    const announcement = formatComparisonAnnouncement(comparison, "Bedroom");
    expect(announcement).toContain("Possible room change detected.");
    expect(announcement).toContain("camera alignment could not be confirmed. Please align the camera and try again.");
  });

  it("generates 'No significant room changes detected.' when status is unchanged", () => {
    const comparison = {
      status: "unchanged",
      comparison: {
        missing: [],
        new: [],
        moved: [],
        unchanged: [{ class_name: "table" }],
      },
    };
    const announcement = formatComparisonAnnouncement(comparison, "Kitchen");
    expect(announcement).toBe("No significant room changes detected.");
  });

  it("generates camera moved voice alert for live monitoring", () => {
    const alert = {
      change_type: "camera_view_changed",
      message: "The camera has moved.",
    };
    const announcement = formatAlertAnnouncement(alert);
    expect(announcement).toContain("Warning! The camera has moved. Monitoring is temporarily paused.");
  });
});

describe("Problem 2: CameraPanel Live Detection and Controls", () => {
  it("renders live detection HUD and object counts when camera is active", () => {
    const liveDetections = [
      { class_name: "bottle", confidence: 0.88, x1: 0.1, y1: 0.2, x2: 0.3, y2: 0.5, zone: "upper-left" },
      { class_name: "chair", confidence: 0.94, x1: 0.5, y1: 0.3, x2: 0.8, y2: 0.9, zone: "middle-right" },
    ];

    render(
      <CameraPanel
        effectiveRoomName="Bedroom"
        cameraActive={true}
        liveDetections={liveDetections}
        knownObjectNames={new Set(["chair"])}
        monitoringState="active"
        lastScanTime="12:30:45 PM"
        videoRef={{ current: document.createElement("video") }}
        canvasRef={{ current: document.createElement("canvas") }}
      />
    );

    // Live HUD displays object count
    expect(screen.getByText("🎯 2 Objects Detected")).toBeTruthy();
    expect(screen.getByText("⏱️ 12:30:45 PM")).toBeTruthy();
    expect(screen.getByText("🟢 Aligned")).toBeTruthy();
  });

  it("renders Test Voice and Replay Voice buttons and fires callback", () => {
    const onTestVoice = vi.fn();
    const onReplayVoice = vi.fn();

    render(
      <CameraPanel
        effectiveRoomName="Bedroom"
        cameraActive={true}
        onTestVoice={onTestVoice}
        onReplayVoice={onReplayVoice}
        videoRef={{ current: document.createElement("video") }}
        canvasRef={{ current: document.createElement("canvas") }}
      />
    );

    const testBtn = screen.getByRole("button", { name: "Test voice announcement" });
    fireEvent.click(testBtn);
    expect(onTestVoice).toHaveBeenCalledTimes(1);

    const replayBtn = screen.getByRole("button", { name: "Replay last voice alert" });
    fireEvent.click(replayBtn);
    expect(onReplayVoice).toHaveBeenCalledTimes(1);
  });
});

describe("Problem 3: Live Change Tracking Against Baseline", () => {
  it("displays missing, moved, new, and unchanged status in LiveObjects", () => {
    const baseline = {
      room_name: "Bedroom",
      detections: [
        { class_name: "bottle", instance_number: 1, confidence: 0.89, zone: "upper-left" },
        { class_name: "chair", instance_number: 1, confidence: 0.95, zone: "middle-center" },
      ],
    };

    const latest = {
      captured_at: "2026-11-18T00:30:00Z",
      detections: [
        { class_name: "chair", instance_number: 1, confidence: 0.92, zone: "lower-right" },
        { class_name: "notebook", instance_number: 1, confidence: 0.84, zone: "upper-right" },
      ],
    };

    const liveComparison = {
      summary: { missing: 1, moved: 1, new: 1, unchanged: 0 },
      missing: [{ class_name: "bottle", zone: "upper-left" }],
      moved: [{ class_name: "chair", original_zone: "middle-center", current_zone: "lower-right" }],
      new: [{ class_name: "notebook", current_zone: "upper-right" }],
      unchanged: [],
    };

    render(
      <LiveObjects
        isActive={true}
        latest={latest}
        baseline={baseline}
        liveComparison={liveComparison}
        knownObjectNames={new Set(["bottle", "chair"])}
        cameraActive={true}
        monitoringState="active"
      />
    );

    // Summary metrics rendered
    expect(screen.getByText("Missing")).toBeTruthy();
    expect(screen.getByText("Moved")).toBeTruthy();
    expect(screen.getByText("New Objects")).toBeTruthy();
    expect(screen.getByText("Unchanged")).toBeTruthy();

    // Specific change cards rendered
    expect(screen.getByText(/Missing from Original Baseline/)).toBeTruthy();
    expect(screen.getByText(/Moved Objects/)).toBeTruthy();
    expect(screen.getByText(/Newly Appeared Objects/)).toBeTruthy();

    // Current detected objects list
    expect(screen.getByText("Objects in Camera View (2)")).toBeTruthy();

    // Baseline reference list
    expect(screen.getByText("Learned Layout for Bedroom (2)")).toBeTruthy();
  });

  it("displays camera moved warning banner when monitoringState is moved", () => {
    render(
      <LiveObjects
        isActive={true}
        latest={{ detections: [] }}
        baseline={{ detections: [] }}
        liveComparison={{ summary: { uncertain: 1 } }}
        cameraActive={true}
        monitoringState="moved"
      />
    );

    expect(screen.getByText("Camera Viewpoint Changed")).toBeTruthy();
    expect(
      screen.getByText(/The camera shifted from the learned room viewpoint/)
    ).toBeTruthy();
  });
});
