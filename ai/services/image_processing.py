import base64
import binascii

import cv2
import numpy as np

from config import MAX_IMAGE_BYTES


def image_from_payload(payload):
    if not isinstance(payload, dict):
        raise ValueError("Send a JSON object with room_name and image fields.")

    image_data = payload.get("image")
    if not isinstance(image_data, str):
        raise ValueError("The camera image must be a base64-encoded data URL.")

    # Accept JPEG or PNG data URLs — OpenCV re-encodes to JPEG for storage
    if not (image_data.startswith("data:image/jpeg;base64,") or
            image_data.startswith("data:image/png;base64,") or
            image_data.startswith("data:image/webp;base64,")):
        raise ValueError(
            "The camera image must be a base64-encoded JPEG, PNG, or WebP data URL."
        )

    encoded_image = image_data.partition(",")[2]
    try:
        image_bytes_raw = base64.b64decode(encoded_image, validate=True)
    except (binascii.Error, ValueError) as error:
        raise ValueError("The camera image is not valid base64 data.") from error

    if not image_bytes_raw or len(image_bytes_raw) > MAX_IMAGE_BYTES:
        raise ValueError("The camera image must be smaller than 8 MB.")

    frame = cv2.imdecode(np.frombuffer(image_bytes_raw, dtype=np.uint8), cv2.IMREAD_COLOR)
    if frame is None:
        raise ValueError("The uploaded image could not be decoded.")

    height, width = frame.shape[:2]
    if width > 4096 or height > 4096:
        raise ValueError("The camera image dimensions must not exceed 4096 by 4096.")

    # Re-encode to JPEG for consistent storage regardless of input format
    ok, jpeg_buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 88])
    if not ok:
        raise ValueError("Could not re-encode the image as JPEG.")
    image_bytes = jpeg_buf.tobytes()

    return image_bytes, frame, width, height
