import math

import cv2
import numpy as np


def camera_view_status(reference_bytes, current_frame):
    reference_frame = cv2.imdecode(
        np.frombuffer(reference_bytes, dtype=np.uint8), cv2.IMREAD_GRAYSCALE
    )
    current_gray = cv2.cvtColor(current_frame, cv2.COLOR_BGR2GRAY)
    if reference_frame is None:
        return "unknown"
    reference_aspect = reference_frame.shape[1] / reference_frame.shape[0]
    current_aspect = current_gray.shape[1] / current_gray.shape[0]
    if abs(reference_aspect - current_aspect) > 0.01:
        return "unknown"
    reference_frame = cv2.resize(
        reference_frame, (current_gray.shape[1], current_gray.shape[0])
    )

    orb = cv2.ORB_create(nfeatures=1000, fastThreshold=12)
    reference_points, reference_descriptors = orb.detectAndCompute(
        reference_frame, None
    )
    current_points, current_descriptors = orb.detectAndCompute(current_gray, None)
    if (
        reference_descriptors is None
        or current_descriptors is None
        or len(reference_points) < 12
        or len(current_points) < 12
    ):
        return "unknown"

    matcher = cv2.BFMatcher(cv2.NORM_HAMMING)
    matches = matcher.knnMatch(reference_descriptors, current_descriptors, k=2)
    good_matches = [
        best
        for pair in matches
        if len(pair) == 2
        for best, second in [pair]
        if best.distance < 0.75 * second.distance
    ]
    if len(good_matches) < 12:
        return "unknown"

    source_points = np.float32(
        [reference_points[match.queryIdx].pt for match in good_matches]
    )
    target_points = np.float32(
        [current_points[match.trainIdx].pt for match in good_matches]
    )
    transform, inlier_mask = cv2.estimateAffinePartial2D(
        source_points,
        target_points,
        method=cv2.RANSAC,
        ransacReprojThreshold=3.0,
        maxIters=2000,
        confidence=0.99,
    )
    if transform is None or inlier_mask is None:
        return "unknown"
    inlier_ratio = float(inlier_mask.mean())
    if inlier_ratio < 0.35:
        return "unknown"

    scale = math.hypot(transform[0, 0], transform[1, 0])
    rotation = abs(math.degrees(math.atan2(transform[1, 0], transform[0, 0])))
    width, height = reference_frame.shape[1], reference_frame.shape[0]
    moved = (
        abs(transform[0, 2]) > width * 0.04
        or abs(transform[1, 2]) > height * 0.04
        or rotation > 3
        or abs(scale - 1) > 0.05
    )
    return "moved" if moved else "stable"
