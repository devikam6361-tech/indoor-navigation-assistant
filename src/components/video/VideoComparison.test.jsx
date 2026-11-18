import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import VideoComparison from "./VideoComparison.jsx";

const fakeVideos = [
  {
    id: "8d212ee1e3c14ad190be168c80644261",
    original_name: "before_room_16sec.mp4",
    duration_seconds: 16.0,
    total_frames: 320,
    extracted_count: 8,
    frames: Array.from({ length: 8 }, (_, i) => ({
      filename: `frame_000${i}.jpg`,
      timestamp_seconds: i * 2,
    })),
  },
  {
    id: "d60ab0339316421c90dede1e5829c5ab",
    original_name: "after_room_16sec.mp4",
    duration_seconds: 16.0,
    total_frames: 320,
    extracted_count: 8,
    frames: Array.from({ length: 8 }, (_, i) => ({
      filename: `frame_000${i}.jpg`,
      timestamp_seconds: i * 2,
    })),
  },
];

const fakeComparison = {
  status: "success",
  before_video_id: "8d212ee1e3c14ad190be168c80644261",
  after_video_id: "d60ab0339316421c90dede1e5829c5ab",
  summary: {
    new: 0,
    missing: 0,
    moved: 1,
    unchanged: 2,
    uncertain: 0,
  },
  detected_changes: [
    {
      title: "Chair (Moved)",
      class_name: "chair",
      confidence: 0.92,
      confidence_percent: 92,
      description: "The chair has changed its position from center to left.",
    },
  ],
  voice_announcement: "The chair has moved from its original position.",
  before_detections: [
    { class_name: "chair", confidence: 0.91, x1: 0.3, y1: 0.38, x2: 0.37, y2: 0.59 },
  ],
  after_detections: [
    { class_name: "chair", confidence: 0.93, x1: 0.14, y1: 0.38, x2: 0.21, y2: 0.59 },
  ],
};

beforeEach(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input, init) => {
      const url = String(input);
      if (url === "/api/videos") {
        return {
          ok: true,
          status: 200,
          headers: { get: () => "application/json" },
          json: async () => ({ videos: fakeVideos }),
        };
      }
      if (url === "/api/videos/compare" && init?.method === "POST") {
        return {
          ok: true,
          status: 200,
          headers: { get: () => "application/json" },
          json: async () => fakeComparison,
        };
      }
      return {
        ok: true,
        status: 200,
        headers: { get: () => "image/jpeg" },
        blob: async () => new Blob([]),
      };
    })
  );

  Object.defineProperty(window, "speechSynthesis", {
    configurable: true,
    value: {
      cancel: vi.fn(),
      speak: vi.fn(),
    },
  });

  window.SpeechSynthesisUtterance = function (text) {
    this.text = text;
  };
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("VideoComparison component", () => {
  it("renders page header and video card titles matching reference", async () => {
    await act(async () => {
      render(<VideoComparison />);
    });

    expect(screen.getByRole("heading", { name: "Video Comparison" })).toBeTruthy();
    expect(screen.getByText("Original Room (Before)")).toBeTruthy();
    expect(screen.getByText("Changed Room (After)")).toBeTruthy();
    expect(screen.getByText("Comparison Results")).toBeTruthy();
    expect(screen.getByText("Detected Change")).toBeTruthy();
    expect(screen.getByText("Voice Alert")).toBeTruthy();
  });

  it("displays comparison summary metrics matching reference", async () => {
    await act(async () => {
      render(<VideoComparison />);
    });

    expect(screen.getByText("New Objects")).toBeTruthy();
    expect(screen.getByText("Missing Objects")).toBeTruthy();
    expect(screen.getByText("Moved Objects")).toBeTruthy();
    expect(screen.getByText("Unchanged Objects")).toBeTruthy();
    expect(screen.getByText("Uncertain Detections")).toBeTruthy();
    expect(screen.getByText("Chair (Moved)")).toBeTruthy();
    expect(screen.getByText("92%")).toBeTruthy();
    expect(
      screen.getByText("The chair has changed its position from center to left.")
    ).toBeTruthy();
  });

  it("replays voice alert when clicking the play button", async () => {
    await act(async () => {
      render(<VideoComparison />);
    });

    const playBtn = screen.getByRole("button", { name: "Replay Voice Announcement" });
    expect(playBtn).toBeTruthy();

    await act(async () => {
      fireEvent.click(playBtn);
    });

    expect(window.speechSynthesis.speak).toHaveBeenCalled();
  });
});
