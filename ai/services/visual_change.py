"""
Visual change detection and region verification service.

Analyzes raw BEFORE and AFTER room images using computer vision (differencing,
contour analysis, and region metrics) to support, verify, and cross-check
object detection comparison results.
"""

import cv2
import numpy as np

from services.visual_recognition import (
    detect_dominant_color,
    measure_region_difference,
    refine_object_label,
)


def extract_changed_regions(before_frame, after_frame, min_contour_area=1200):
    """
    Computes visual difference between two aligned frames and returns bounding
    boxes of significantly changed regions: [(x1, y1, x2, y2), ...].
    """
    if before_frame is None or after_frame is None:
        return []

    # Ensure identical shape
    if before_frame.shape[:2] != after_frame.shape[:2]:
        after_frame = cv2.resize(
            after_frame, (before_frame.shape[1], before_frame.shape[0])
        )

    # Convert to grayscale and blur to eliminate minor camera noise
    gray_before = cv2.cvtColor(before_frame, cv2.COLOR_BGR2GRAY)
    gray_after = cv2.cvtColor(after_frame, cv2.COLOR_BGR2GRAY)

    # Normalize lighting via histogram matching / equalized luminance
    blur_before = cv2.GaussianBlur(gray_before, (5, 5), 0)
    blur_after = cv2.GaussianBlur(gray_after, (5, 5), 0)

    diff = cv2.absdiff(blur_before, blur_after)
    _, thresh = cv2.threshold(diff, 25, 255, cv2.THRESH_BINARY)

    # Morphological closing to merge nearby fragmented changes
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (9, 9))
    cleaned = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel)

    contours, _ = cv2.findContours(
        cleaned, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )

    h, w = before_frame.shape[:2]
    changed_boxes = []
    for c in contours:
        area = cv2.contourArea(c)
        if area >= min_contour_area:
            bx, by, bw, bh = cv2.boundingRect(c)
            # Normalize to pixels within frame
            x1 = max(0, bx)
            y1 = max(0, by)
            x2 = min(w, bx + bw)
            y2 = min(h, by + bh)
            changed_boxes.append((x1, y1, x2, y2))

    return changed_boxes


def compute_overall_visual_change_ratio(before_frame, after_frame):
    """
    Returns the percentage of pixels that changed significantly between frames.
    """
    if before_frame is None or after_frame is None:
        return 0.0

    if before_frame.shape[:2] != after_frame.shape[:2]:
        after_frame = cv2.resize(
            after_frame, (before_frame.shape[1], before_frame.shape[0])
        )

    gray_before = cv2.cvtColor(before_frame, cv2.COLOR_BGR2GRAY)
    gray_after = cv2.cvtColor(after_frame, cv2.COLOR_BGR2GRAY)

    diff = cv2.absdiff(gray_before, gray_after)
    _, thresh = cv2.threshold(diff, 25, 255, cv2.THRESH_BINARY)
    return float(np.count_nonzero(thresh)) / thresh.size


def verify_object_visibility_change(
    detection, before_frame, after_frame, width, height
):
    """
    Given a detection in BEFORE, measures if its region visually changed in AFTER.
    Returns (is_visually_cleared, change_ratio).
    """
    x1 = int(max(0.0, detection.get("x1", 0.0)) * width)
    y1 = int(max(0.0, detection.get("y1", 0.0)) * height)
    x2 = int(min(1.0, detection.get("x2", 1.0)) * width)
    y2 = int(min(1.0, detection.get("y2", 1.0)) * height)

    if x2 <= x1 or y2 <= y1:
        return False, 0.0

    before_crop = before_frame[y1:y2, x1:x2]
    after_crop = after_frame[y1:y2, x1:x2]

    change_ratio, _ = measure_region_difference(before_crop, after_crop)
    # If over 20% of pixels in this object's region changed, visual evidence confirms removal/change
    return change_ratio >= 0.20, change_ratio
