import csv
import json
import time
from pathlib import Path

from ultralytics import YOLO


ROOT_DIR = Path(__file__).resolve().parent.parent
MODEL_PATHS = {
    "yolo11n": ROOT_DIR / "yolo11n.pt",
    "yolo11s": ROOT_DIR / "yolo11s.pt",
}
IMAGE_DIR = ROOT_DIR / "scratch_eval_images"
RESULTS_PATH = Path(__file__).resolve().parent / "yolo_evaluation_results.csv"

IMAGE_SIZE = 640
CONFIDENCE_THRESHOLD = 0.25
IOU_THRESHOLD = 0.7
WARMUP_RUNS = 2
MEASURED_RUNS = 3


def infer(model, image_path):
    start = time.perf_counter()
    result = model.predict(
        source=str(image_path),
        imgsz=IMAGE_SIZE,
        conf=CONFIDENCE_THRESHOLD,
        iou=IOU_THRESHOLD,
        device="cpu",
        verbose=False,
    )[0]
    elapsed_ms = (time.perf_counter() - start) * 1000

    detections = []
    for box in result.boxes:
        class_id = int(box.cls[0].item())
        detections.append(
            {
                "class_name": result.names[class_id],
                "confidence": float(box.conf[0].item()),
            }
        )

    return elapsed_ms, detections


def main():
    image_paths = sorted(
        path
        for path in IMAGE_DIR.iterdir()
        if path.is_file() and path.suffix.lower() in {".jpg", ".jpeg", ".png"}
    )
    if len(image_paths) != 9:
        raise RuntimeError(
            f"Expected 9 evaluation images in {IMAGE_DIR}, found {len(image_paths)}."
        )

    rows = []
    results_by_model = {}

    for model_name, model_path in MODEL_PATHS.items():
        if not model_path.is_file():
            raise FileNotFoundError(f"Model weights not found: {model_path}")

        print(f"Loading {model_name} from {model_path}")
        model = YOLO(str(model_path))

        for _ in range(WARMUP_RUNS):
            infer(model, image_paths[0])

        results_by_model[model_name] = {}
        for image_path in image_paths:
            measured = []
            for run_number in range(1, MEASURED_RUNS + 1):
                elapsed_ms, detections = infer(model, image_path)
                measured.append(
                    {
                        "inference_time_ms": elapsed_ms,
                        "detections": detections,
                    }
                )
                rows.append(
                    {
                        "model": model_name,
                        "image": image_path.name,
                        "run": run_number,
                        "inference_time_ms": f"{elapsed_ms:.3f}",
                        "num_detections": len(detections),
                        "class_names": json.dumps(
                            [detection["class_name"] for detection in detections]
                        ),
                        "confidence_scores": json.dumps(
                            [
                                round(detection["confidence"], 6)
                                for detection in detections
                            ]
                        ),
                    }
                )
            results_by_model[model_name][image_path.name] = measured

    with RESULTS_PATH.open("w", newline="", encoding="utf-8") as csv_file:
        fieldnames = [
            "model",
            "image",
            "run",
            "inference_time_ms",
            "num_detections",
            "class_names",
            "confidence_scores",
        ]
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print("\nImage-by-image comparison (detection details are listed per run):")
    for image_path in image_paths:
        print(f"\n{image_path.name}")
        for model_name in MODEL_PATHS:
            measured = results_by_model[model_name][image_path.name]
            mean_ms = sum(
                run["inference_time_ms"] for run in measured
            ) / MEASURED_RUNS
            details_by_run = [
                [
                    f"{detection['class_name']}:{detection['confidence']:.3f}"
                    for detection in run["detections"]
                ]
                for run in measured
            ]
            counts_by_run = [
                len(run["detections"]) for run in measured
            ]
            print(
                f"  {model_name}: mean={mean_ms:.3f} ms, "
                f"detections/run={counts_by_run}, details/run={details_by_run}"
            )

    print("\nModel summaries:")
    for model_name in MODEL_PATHS:
        model_rows = [row for row in rows if row["model"] == model_name]
        average_ms = sum(
            float(row["inference_time_ms"]) for row in model_rows
        ) / len(model_rows)
        total_detections = sum(
            int(row["num_detections"]) for row in model_rows
        )
        print(
            f"  {model_name}: average inference time={average_ms:.3f} ms "
            f"({len(model_rows)} measured runs), "
            f"total detections={total_detections} across measured runs"
        )

    print(f"\nCSV results saved to {RESULTS_PATH}")


if __name__ == "__main__":
    main()
