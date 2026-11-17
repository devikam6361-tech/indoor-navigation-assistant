import math

import cv2
import numpy as np


import math

import cv2
import numpy as np


def normalize_illumination(gray_image):
    """
    Applies CLAHE (Contrast Limited Adaptive Histogram Equalization) to normalize
    illumination variations (shadows, exposure shifts, room lighting changes)
    while preserving edge structures for feature detection.
    """
    if gray_image is None or gray_image.size == 0:
        return gray_image
    clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))
    return clahe.apply(gray_image)


def check_image_blur(gray_image):
    """
    Evaluates image sharpness using Laplacian variance on normalized contrast.
    Returns (sharpness_variance, is_blurry).
    """
    if gray_image is None or gray_image.size == 0:
        return 0.0, True
    norm = normalize_illumination(gray_image)
    variance = float(cv2.Laplacian(norm, cv2.CV_64F).var())
    return variance, variance < 10.0


def validate_camera_view(reference_input, current_frame, normalize_lighting=True):
    """
    Comprehensive camera view analysis.
    Distinguishes:
      - 'stable': Geometry is consistent; minor vibration within tolerance.
      - 'moved': Genuine geometric camera movement (excessive rotation, translation, or zoom).
      - 'unknown': Mismatched scene, heavy occlusion, featureless surface, or severe blur.

    Also separates and reports illumination changes without mistaking them for camera movement.
    """
    # 1. Decode reference image if bytes provided
    if isinstance(reference_input, (bytes, bytearray)):
        reference_frame = cv2.imdecode(
            np.frombuffer(reference_input, dtype=np.uint8), cv2.IMREAD_GRAYSCALE
        )
    elif isinstance(reference_input, np.ndarray):
        if len(reference_input.shape) == 3:
            reference_frame = cv2.cvtColor(reference_input, cv2.COLOR_BGR2GRAY)
        else:
            reference_frame = reference_input.copy()
    else:
        return {
            "status": "unknown",
            "reason": "invalid_reference_input",
            "illumination_changed": False,
            "can_compare": False,
            "transform": None,
        }

    if reference_frame is None or current_frame is None:
        return {
            "status": "unknown",
            "reason": "missing_frame",
            "illumination_changed": False,
            "can_compare": False,
            "transform": None,
        }

    # 2. Convert current frame to grayscale
    if len(current_frame.shape) == 3:
        current_gray = cv2.cvtColor(current_frame, cv2.COLOR_BGR2GRAY)
    else:
        current_gray = current_frame.copy()

    # 3. Check aspect ratios
    reference_aspect = reference_frame.shape[1] / reference_frame.shape[0]
    current_aspect = current_gray.shape[1] / current_gray.shape[0]
    if abs(reference_aspect - current_aspect) > 0.01:
        return {
            "status": "unknown",
            "reason": "aspect_ratio_mismatch",
            "illumination_changed": False,
            "can_compare": False,
            "transform": None,
        }

    # Match dimensions
    if reference_frame.shape != current_gray.shape:
        reference_frame = cv2.resize(
            reference_frame, (current_gray.shape[1], current_gray.shape[0])
        )

    width, height = reference_frame.shape[1], reference_frame.shape[0]

    # 4. Check for extreme blur / featureless flat images
    ref_sharpness, ref_blurry = check_image_blur(reference_frame)
    cur_sharpness, cur_blurry = check_image_blur(current_gray)
    if ref_blurry or cur_blurry:
        return {
            "status": "unknown",
            "reason": "severe_blur_or_flat_image",
            "illumination_changed": False,
            "can_compare": False,
            "transform": None,
            "ref_sharpness": ref_sharpness,
            "cur_sharpness": cur_sharpness,
        }

    # 5. Measure illumination shift
    mean_ref = float(np.mean(reference_frame))
    mean_cur = float(np.mean(current_gray))
    luminance_diff = abs(mean_ref - mean_cur)
    is_illumination_changed = luminance_diff > 22.0

    # 6. Feature detection using ORB (with illumination normalization if requested)
    if normalize_lighting:
        detect_ref = normalize_illumination(reference_frame)
        detect_cur = normalize_illumination(current_gray)
    else:
        detect_ref = reference_frame
        detect_cur = current_gray

    orb = cv2.ORB_create(nfeatures=1200, fastThreshold=10)
    reference_points, reference_descriptors = orb.detectAndCompute(
        detect_ref, None
    )
    current_points, current_descriptors = orb.detectAndCompute(detect_cur, None)

    if (
        reference_descriptors is None
        or current_descriptors is None
        or len(reference_points) < 12
        or len(current_points) < 12
    ):
        return {
            "status": "unknown",
            "reason": "insufficient_features",
            "illumination_changed": is_illumination_changed,
            "can_compare": False,
            "transform": None,
        }

    # 7. Descriptor matching with Lowe's ratio test
    matcher = cv2.BFMatcher(cv2.NORM_HAMMING)
    matches = matcher.knnMatch(reference_descriptors, current_descriptors, k=2)
    good_matches = [
        best
        for pair in matches
        if len(pair) == 2
        for best, second in [pair]
        if best.distance < 0.78 * second.distance
    ]

    if len(good_matches) < 12:
        return {
            "status": "unknown",
            "reason": "insufficient_matches",
            "good_matches_count": len(good_matches),
            "illumination_changed": is_illumination_changed,
            "can_compare": False,
            "transform": None,
        }

    # 8. Robust Partial Affine Transformation Estimation (RANSAC)
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
        ransacReprojThreshold=3.5,
        maxIters=2000,
        confidence=0.99,
    )

    if transform is None or inlier_mask is None:
        return {
            "status": "unknown",
            "reason": "transform_estimation_failed",
            "illumination_changed": is_illumination_changed,
            "can_compare": False,
            "transform": None,
        }

    inlier_ratio = float(inlier_mask.mean())
    inliers_count = int(inlier_mask.sum())
    if inlier_ratio < 0.32 or inliers_count < 8:
        return {
            "status": "unknown",
            "reason": "mismatched_view",
            "inlier_ratio": inlier_ratio,
            "inliers_count": inliers_count,
            "illumination_changed": is_illumination_changed,
            "can_compare": False,
            "transform": None,
        }

    # 9. Extract geometric motion components
    scale = float(math.hypot(transform[0, 0], transform[1, 0]))
    rotation = float(abs(math.degrees(math.atan2(transform[1, 0], transform[0, 0]))))
    norm_trans = float(math.hypot(transform[0, 2] / width, transform[1, 2] / height))

    # Thresholds:
    # Minor camera vibration / typing jitter: norm_trans <= 0.065, rotation <= 3.5 deg, scale <= 6%
    is_moved = (
        norm_trans > 0.065
        or rotation > 3.5
        or abs(scale - 1.0) > 0.06
    )

    status = "moved" if is_moved else "stable"
    reason = "geometric_movement" if is_moved else (
        "illumination_change_stable" if is_illumination_changed else "stable_view"
    )

    return {
        "status": status,
        "reason": reason,
        "illumination_changed": is_illumination_changed,
        "mean_luminance_diff": round(luminance_diff, 1),
        "inlier_ratio": round(inlier_ratio, 3),
        "inliers_count": inliers_count,
        "rotation_deg": round(rotation, 2),
        "translation_norm": round(norm_trans, 4),
        "scale": round(scale, 3),
        "transform": transform,
        "can_compare": status == "stable",
    }


def align_frames_if_needed(reference_frame, current_frame, transform=None):
    """
    Aligns current_frame to reference_frame coordinates using the affine transform.
    Returns the geometrically aligned frame.
    """
    if reference_frame is None or current_frame is None:
        return current_frame

    h, w = reference_frame.shape[:2]
    if transform is None:
        analysis = validate_camera_view(reference_frame, current_frame)
        transform = analysis.get("transform")

    if transform is not None:
        # Invert target_points -> source_points mapping to align current onto reference
        inv_transform = cv2.invertAffineTransform(transform)
        aligned = cv2.warpAffine(
            current_frame,
            inv_transform,
            (w, h),
            flags=cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_REFLECT,
        )
        return aligned

    return current_frame


def camera_view_status(reference_bytes, current_frame):
    """
    Backward-compatible entry point returning 'stable', 'moved', or 'unknown'.
    """
    result = validate_camera_view(reference_bytes, current_frame)
    return result["status"]
