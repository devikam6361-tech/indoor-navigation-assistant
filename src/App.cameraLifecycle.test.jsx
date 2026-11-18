import { StrictMode } from "react";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App.jsx";

function createDeferred() {
  let resolve;
  let reject;
  const promise = new Promise((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

function createFakeStream(trackCount = 3) {
  const tracks = Array.from({ length: trackCount }, () => ({
    stop: vi.fn(),
  }));
  return {
    tracks,
    stream: { getTracks: () => tracks },
  };
}

function jsonResponse(payload) {
  return {
    ok: true,
    status: 200,
    headers: { get: () => "application/json" },
    json: async () => payload,
  };
}

let originalMediaDevicesDescriptor;
let originalSrcObjectDescriptor;
let originalPlayDescriptor;
let originalSpeechSynthesisDescriptor;

beforeEach(() => {
  originalMediaDevicesDescriptor = Object.getOwnPropertyDescriptor(
    navigator,
    "mediaDevices",
  );
  Object.defineProperty(navigator, "mediaDevices", {
    configurable: true,
    value: { getUserMedia: vi.fn() },
  });

  originalSrcObjectDescriptor = Object.getOwnPropertyDescriptor(
    HTMLMediaElement.prototype,
    "srcObject",
  );
  Object.defineProperty(HTMLMediaElement.prototype, "srcObject", {
    configurable: true,
    get() {
      return this._testSrcObject || null;
    },
    set(value) {
      this._testSrcObject = value;
    },
  });

  originalPlayDescriptor = Object.getOwnPropertyDescriptor(
    HTMLMediaElement.prototype,
    "play",
  );
  Object.defineProperty(HTMLMediaElement.prototype, "play", {
    configurable: true,
    value: vi.fn().mockResolvedValue(undefined),
    writable: true,
  });

  originalSpeechSynthesisDescriptor = Object.getOwnPropertyDescriptor(
    window,
    "speechSynthesis",
  );
  Object.defineProperty(window, "speechSynthesis", {
    configurable: true,
    value: { cancel: vi.fn(), speak: vi.fn() },
  });

  vi.stubGlobal(
    "fetch",
    vi.fn(async (input) => {
      const url = String(input);
      if (url.startsWith("/api/baseline?")) {
        return jsonResponse({ baseline: null });
      }
      if (url.startsWith("/api/latest?")) {
        return jsonResponse({ latest: null, history: [] });
      }
      if (url === "/api/rooms") {
        return jsonResponse({ rooms: [] });
      }
      if (url.startsWith("/api/layouts?")) {
        return jsonResponse({ layouts: [] });
      }
      throw new Error(`Unexpected API request in camera lifecycle test: ${url}`);
    }),
  );
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();

  if (originalMediaDevicesDescriptor) {
    Object.defineProperty(navigator, "mediaDevices", originalMediaDevicesDescriptor);
  } else {
    delete navigator.mediaDevices;
  }

  if (originalSrcObjectDescriptor) {
    Object.defineProperty(
      HTMLMediaElement.prototype,
      "srcObject",
      originalSrcObjectDescriptor,
    );
  } else {
    delete HTMLMediaElement.prototype.srcObject;
  }

  if (originalPlayDescriptor) {
    Object.defineProperty(HTMLMediaElement.prototype, "play", originalPlayDescriptor);
  } else {
    delete HTMLMediaElement.prototype.play;
  }

  if (originalSpeechSynthesisDescriptor) {
    Object.defineProperty(
      window,
      "speechSynthesis",
      originalSpeechSynthesisDescriptor,
    );
  } else {
    delete window.speechSynthesis;
  }
});

async function renderReadyApp() {
  const rendered = render(
    <StrictMode>
      <App />
    </StrictMode>,
  );
  const startButton = await screen.findByRole("button", {
    name: "Start monitoring camera",
  });
  await waitFor(() => expect(startButton.disabled).toBe(false));
  return rendered;
}

async function resolveCameraStartup(permission, stream) {
  await act(async () => {
    permission.resolve(stream);
    await permission.promise;
  });

  const video = document.querySelector("video");
  await waitFor(() => expect(video.srcObject).toBe(stream));

  await act(async () => {
    video.dispatchEvent(new Event("loadedmetadata"));
    await Promise.resolve();
  });
}

function expectEveryTrackStopped(tracks) {
  for (const track of tracks) {
    expect(track.stop).toHaveBeenCalledTimes(1);
  }
}

describe("camera lifecycle", () => {
  it("cancels a pending permission request without activating the late stream", async () => {
    const permission = createDeferred();
    const { tracks, stream } = createFakeStream();
    const getUserMedia = vi.fn(() => permission.promise);
    navigator.mediaDevices.getUserMedia = getUserMedia;

    await renderReadyApp();
    fireEvent.click(screen.getByRole("button", { name: "Start monitoring camera" }));
    fireEvent.click(screen.getByRole("button", { name: "Cancel camera startup" }));

    expect(screen.getByText("Canceling startup")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Cancel camera startup" }).disabled).toBe(true);

    await act(async () => {
      permission.resolve(stream);
      await permission.promise;
    });

    await waitFor(() => expectEveryTrackStopped(tracks));
    expect(screen.getByText("Camera off")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Stop monitoring camera" })).toBeNull();
  });

  it("stops every track when permission resolves after unmount", async () => {
    const permission = createDeferred();
    const { tracks, stream } = createFakeStream();
    navigator.mediaDevices.getUserMedia = vi.fn(() => permission.promise);

    const { unmount } = await renderReadyApp();
    fireEvent.click(screen.getByRole("button", { name: "Start monitoring camera" }));
    unmount();

    await act(async () => {
      permission.resolve(stream);
      await permission.promise;
    });

    await waitFor(() => expectEveryTrackStopped(tracks));
  });

  it("issues only one getUserMedia request for rapid Start events", async () => {
    const permission = createDeferred();
    const { tracks, stream } = createFakeStream();
    const startButton = await (async () => {
      await renderReadyApp();
      return screen.getByRole("button", { name: "Start monitoring camera" });
    })();

    let dispatchedAgain = false;
    const getUserMedia = vi.fn(() => {
      if (!dispatchedAgain) {
        dispatchedAgain = true;
        startButton.dispatchEvent(new MouseEvent("click", { bubbles: true }));
      }
      return permission.promise;
    });
    navigator.mediaDevices.getUserMedia = getUserMedia;

    fireEvent.click(startButton);
    expect(getUserMedia).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole("button", { name: "Cancel camera startup" }));
    await act(async () => {
      permission.resolve(stream);
      await permission.promise;
    });
    await waitFor(() => expectEveryTrackStopped(tracks));
  });

  it("starts normally and stops all tracks when Stop is clicked", async () => {
    const permission = createDeferred();
    const { tracks, stream } = createFakeStream();
    navigator.mediaDevices.getUserMedia = vi.fn(() => permission.promise);

    await renderReadyApp();
    fireEvent.click(screen.getByRole("button", { name: "Start monitoring camera" }));
    await resolveCameraStartup(permission, stream);

    expect(screen.getByText("Camera on")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Stop monitoring camera" }));

    expectEveryTrackStopped(tracks);
    expect(document.querySelector("video").srcObject).toBeNull();
    expect(screen.getByText("Camera off")).toBeTruthy();
  });

  it("stops every track when a canceled getUserMedia request resolves late", async () => {
    const permission = createDeferred();
    const { tracks, stream } = createFakeStream(4);
    navigator.mediaDevices.getUserMedia = vi.fn(() => permission.promise);

    await renderReadyApp();
    fireEvent.click(screen.getByRole("button", { name: "Start monitoring camera" }));
    fireEvent.click(screen.getByRole("button", { name: "Cancel camera startup" }));

    await act(async () => {
      permission.resolve(stream);
      await permission.promise;
    });

    await waitFor(() => expectEveryTrackStopped(tracks));
    expect(screen.getByText("Camera off")).toBeTruthy();
  });
});
