from pathlib import Path

import cv2
from ultralytics import YOLO


ROOT_DIR = Path(__file__).resolve().parent.parent
IMAGE_DIR = ROOT_DIR / "scratch_eval_images"
OUTPUT_DIR = Path(__file__).resolve().parent / "evaluation_output" / "curated"
CURATED_IMAGES = (
    "dining_room_chairs.jpg",
    "living_room_plant.jpg",
    "living_room_sofa_table.jpg",
    "sofa_plants.jpg",
)
MODEL_PATHS = {
    "yolo11n": ROOT_DIR / "yolo11n.pt",
    "yolo11s": ROOT_DIR / "yolo11s.pt",
}

CONFIDENCE_THRESHOLD = 0.25
IMAGE_SIZE = 640
IOU_THRESHOLD = 0.7


def main():
    image_paths = [IMAGE_DIR / image_name for image_name in CURATED_IMAGES]
    missing_images = [path for path in image_paths if not path.is_file()]
    if missing_images:
        missing_list = ", ".join(str(path) for path in missing_images)
        raise FileNotFoundError(f"Curated evaluation images not found: {missing_list}")

    for model_name, model_path in MODEL_PATHS.items():
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

    print(f"\nCurated comparison images saved under {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
