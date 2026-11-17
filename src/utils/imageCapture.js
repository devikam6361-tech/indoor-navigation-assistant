// Captures a guaranteed-JPEG data-URL from a live <video> element.
// Falls back through a Blob/createObjectURL path when the browser
// returns PNG from toDataURL (e.g. certain Firefox builds).

export async function captureJpegFromVideo(video, quality = 0.82) {
  const offscreen = document.createElement("canvas");
  const scale = Math.min(1, 1280 / video.videoWidth, 720 / video.videoHeight);
  offscreen.width = Math.round(video.videoWidth * scale);
  offscreen.height = Math.round(video.videoHeight * scale);
  const ctx = offscreen.getContext("2d");
  if (!ctx) throw new Error("Could not create canvas context from webcam frame.");
  ctx.drawImage(video, 0, 0, offscreen.width, offscreen.height);
  const dataUrl = offscreen.toDataURL("image/jpeg", quality);
  if (dataUrl.startsWith("data:image/jpeg;base64,")) return dataUrl;

  // Browser produced PNG — convert using a Blob and createObjectURL so the
  // image is fully decoded before we draw it onto the fallback canvas.
  return new Promise((resolve, reject) => {
    offscreen.toBlob((blob) => {
      if (!blob) { reject(new Error("Canvas toBlob failed.")); return; }
      const url = URL.createObjectURL(blob);
      const img = new Image();
      img.onload = () => {
        URL.revokeObjectURL(url);
        const fb = document.createElement("canvas");
        fb.width = offscreen.width;
        fb.height = offscreen.height;
        const ctx2 = fb.getContext("2d");
        ctx2.drawImage(img, 0, 0);
        const jpeg = fb.toDataURL("image/jpeg", quality);
        if (!jpeg.startsWith("data:image/jpeg;base64,")) {
          reject(new Error("Browser cannot produce a JPEG from the webcam. Try Chrome or Edge."));
        } else {
          resolve(jpeg);
        }
      };
      img.onerror = () => {
        URL.revokeObjectURL(url);
        reject(new Error("Could not re-encode webcam frame as JPEG."));
      };
      img.src = url;
    }, "image/png");
  });
}
