"""
Visual recognition and semantic attribute refinement service.

Enriches raw COCO detection labels (e.g. 'teddy bear', 'backpack', 'bottle')
using visual attributes such as color and texture from actual image crops.
Also provides crop-level visual difference analysis.
"""

import cv2
import numpy as np


def detect_dominant_color(bgr_crop):
    """
    Identifies notable dominant color in an image crop using HSV color space.
    Returns color name string or None if neutral/indeterminate.
    """
    if bgr_crop is None or bgr_crop.size == 0:
        return None

    hsv = cv2.cvtColor(bgr_crop, cv2.COLOR_BGR2HSV)
    h, s, v = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]
    total_pixels = bgr_crop.shape[0] * bgr_crop.shape[1]
    if total_pixels == 0:
        return None

    # Color ranges in standard OpenCV HSV (H: 0-180, S: 0-255, V: 0-255)
    # Pink: Magenta/Rose hues ~140-175, good saturation and brightness
    pink_mask = (h >= 140) & (h <= 175) & (s >= 30) & (v >= 65)
    pink_ratio = float(np.count_nonzero(pink_mask)) / total_pixels

    # Red: Wrap-around 0-10 and 170-180 with higher saturation
    red_mask = ((h <= 10) | (h >= 170)) & (s >= 55) & (v >= 60)
    red_ratio = float(np.count_nonzero(red_mask)) / total_pixels

    # Blue: 95-130
    blue_mask = (h >= 95) & (h <= 130) & (s >= 40) & (v >= 50)
    blue_ratio = float(np.count_nonzero(blue_mask)) / total_pixels

    # Green: 35-85
    green_mask = (h >= 35) & (h <= 85) & (s >= 40) & (v >= 50)
    green_ratio = float(np.count_nonzero(green_mask)) / total_pixels

    # Yellow: 20-35
    yellow_mask = (h >= 20) & (h <= 35) & (s >= 50) & (v >= 90)
    yellow_ratio = float(np.count_nonzero(yellow_mask)) / total_pixels

    # Brown / Tan: 10-25 with lower value or moderate saturation
    brown_mask = (h >= 10) & (h <= 25) & (s >= 35) & (s <= 180) & (v >= 40) & (v <= 180)
    brown_ratio = float(np.count_nonzero(brown_mask)) / total_pixels

    if pink_ratio >= 0.07:
        return "pink"
    if blue_ratio >= 0.15:
        return "blue"
    if green_ratio >= 0.15:
        return "green"
    if red_ratio >= 0.12:
        return "red"
    if yellow_ratio >= 0.12:
        return "yellow"
    if brown_ratio >= 0.18:
        return "brown"

    return None


def refine_object_label(base_class, bgr_crop=None):
    """
    Refines generic COCO class names into descriptive, human-friendly labels.
    e.g. COCO class 'teddy bear' with pink color -> 'pink plush doll'
    """
    clean_name = base_class.lower().strip()

    if clean_name in {"teddy bear", "toy", "doll", "plush toy", "plush doll"}:
        color = detect_dominant_color(bgr_crop) if bgr_crop is not None else None
        if color == "pink":
            return "pink plush doll"
        if color:
            return f"{color} plush toy"
        return "plush doll"

    if clean_name in {"backpack", "handbag", "bottle"}:
        color = detect_dominant_color(bgr_crop) if bgr_crop is not None else None
        if color:
            return f"{color} {clean_name}"

    return clean_name


def measure_region_difference(before_crop, after_crop):
    """
    Measures the visual difference between two crops of the same region.
    Returns (change_ratio, mean_diff).
    """
    if before_crop is None or after_crop is None:
        return 1.0, 255.0
    if before_crop.size == 0 or after_crop.size == 0:
        return 1.0, 255.0

    # Ensure identical dimensions
    if before_crop.shape != after_crop.shape:
        after_crop = cv2.resize(
            after_crop, (before_crop.shape[1], before_crop.shape[0])
        )

    diff = cv2.absdiff(before_crop, after_crop)
    gray_diff = cv2.cvtColor(diff, cv2.COLOR_BGR2GRAY)
    mean_diff = float(gray_diff.mean())

    # Pixel threshold: difference > 25 intensity values counts as changed
    _, thresh = cv2.threshold(gray_diff, 25, 255, cv2.THRESH_BINARY)
    change_ratio = float(np.count_nonzero(thresh)) / thresh.size

    return round(change_ratio, 3), round(mean_diff, 1)
