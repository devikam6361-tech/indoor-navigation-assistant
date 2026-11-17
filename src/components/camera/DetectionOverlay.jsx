import { useEffect, useRef } from "react";

// Renders a <canvas> that draws YOLO bounding boxes over a room image.
// Props:
//   imageUrl   — data-URL of the JPEG to display
//   detections — array of detection objects from the Flask API
//   label      — accessible label for the canvas (shown above and as aria-label)
export default function DetectionOverlay({ imageUrl, detections, label }) {
  const canvasRef = useRef(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !imageUrl) return;
    const img = new Image();
    img.onload = () => {
      const ctx = canvas.getContext("2d");
      canvas.width = img.naturalWidth;
      canvas.height = img.naturalHeight;
      ctx.drawImage(img, 0, 0);
      if (detections && detections.length) {
        detections.forEach((det) => {
          const x = det.x1 * img.naturalWidth;
          const y = det.y1 * img.naturalHeight;
          const w = (det.x2 - det.x1) * img.naturalWidth;
          const h = (det.y2 - det.y1) * img.naturalHeight;
          ctx.strokeStyle = "#2d9c5e";
          ctx.lineWidth = 2;
          ctx.strokeRect(x, y, w, h);
          ctx.fillStyle = "rgba(45,156,94,0.85)";
          const text = `${det.class_name} ${Math.round(det.confidence * 100)}%`;
          ctx.font = `bold ${Math.max(11, img.naturalWidth / 60)}px sans-serif`;
          const tw = ctx.measureText(text).width + 6;
          ctx.fillRect(
            x,
            y - Math.max(16, img.naturalHeight / 35),
            tw,
            Math.max(16, img.naturalHeight / 35),
          );
          ctx.fillStyle = "#fff";
          ctx.fillText(text, x + 3, y - 3);
        });
      }
    };
    img.src = imageUrl;
  }, [imageUrl, detections]);

  return (
    <div className="overlay-wrapper">
      <p className="overlay-label">{label}</p>
      <canvas
        ref={canvasRef}
        className="detection-canvas"
        aria-label={label}
        role="img"
      />
    </div>
  );
}
