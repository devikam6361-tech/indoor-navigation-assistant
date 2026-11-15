from pathlib import Path

import cv2
from ultralytics import YOLO


ROOT_DIR = Path(__file__).resolve().parent.parent
MODEL_OUTPUTS = {
    "yolo11n": ROOT_DIR / "yolo11n.pt",
    "yolo11s": ROOT_DIR / "yolo11s.pt",
}
IMAGE_DIR = ROOT_DIR / "scratch_eval_images"
OUTPUT_DIR = Path(__file__).resolve().parent / "evaluation_output"

IMAGE_SIZE = 640
CONFIDENCE_THRESHOLD = 0.25
IOU_THRESHOLD = 0.7
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png"}


def main():
    image_paths = sorted(
        path
        for path in IMAGE_DIR.iterdir()
        if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
    )
    if len(image_paths) != 9:
        raise RuntimeError(
            f"Expected 9 evaluation images in {IMAGE_DIR}, found {len(image_paths)}."
        )

    for model_name, model_path in MODEL_OUTPUTS.items():
        if not model_path.is_file():
            raise FileNotFoundError(f"Model weights not found: {model_path}")

        model_output_dir = OUTPUT_DIR / model_name
        model_output_dir.mkdir(parents=True, exist_ok=True)

        print(f"Loading {model_name} from {model_path}")
        model = YOLO(str(model_path))

        for image_path in image_paths:
            result = model.predict(
                source=str(image_path),
                imgsz=IMAGE_SIZE,
                conf=CONFIDENCE_THRESHOLD,
                iou=IOU_THRESHOLD,
                device="cpu",
                verbose=False,
            )[0]
            annotated_image = result.plot(labels=True, conf=True)
            output_path = model_output_dir / image_path.name
            if not cv2.imwrite(str(output_path), annotated_image):
                raise OSError(f"Could not save annotated image: {output_path}")
            print(f"Saved {output_path}")

    print(f"\nAnnotated comparisons saved under {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
