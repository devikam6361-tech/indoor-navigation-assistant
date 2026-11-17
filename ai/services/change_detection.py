import math

from config import (
    CANDIDATE_CONFIDENCE_THRESHOLD,
    CONFIDENCE_THRESHOLD,
    MONITORED_CLASSES,
    MOVE_DISTANCE_THRESHOLD,
    SUPPORTED_CLASSES,
)
from services.visual_change import (
    compute_overall_visual_change_ratio,
    verify_object_visibility_change,
)
from utils.formatting import event_response, image_zone, zone_label


OPEN_VOCABULARY_CLASSES = {
    "calculator",
    "doll",
    "dustbin",
    "geometry box",
    "medicine bottle",
    "microscope",
    "notebook",
    "pillow",
    "pink plush doll",
    "pink plush toy",
    "plush doll",
    "plush toy",
    "slippers",
    "test tube",
    "toy",
    "trash bin",
    "unfamiliar household object",
    "unknown object",
    "wardrobe",
}


def is_monitored_class(name):
    if not isinstance(name, str):
        return False
    clean = name.strip().lower()
    if clean in MONITORED_CLASSES or clean in OPEN_VOCABULARY_CLASSES:
        return True
    return False


def compare_detections(baseline, current):
    candidates = []
    classes = {
        item["class_name"]
        for item in baseline + current
        if is_monitored_class(item["class_name"])
    }

    for name in classes:
        matched_baseline = set()
        matched_current = set()
        original = sorted(
            (item for item in baseline if item["class_name"] == name),
            key=lambda item: item["instance_number"],
        )
        observed = sorted(
            (item for item in current if item["class_name"] == name),
            key=lambda item: (item["center_y"], item["center_x"]),
        )
        distances = sorted(
            (
                math.hypot(
                    old["center_x"] - new["center_x"],
                    old["center_y"] - new["center_y"],
                ),
                old_index,
                new_index,
            )
            for old_index, old in enumerate(original)
            for new_index, new in enumerate(observed)
        )
        pairs = []
        for distance, old_index, new_index in distances:
            if old_index in matched_baseline or new_index in matched_current:
                continue
            if distance <= MOVE_DISTANCE_THRESHOLD:
                matched_baseline.add(old_index)
                matched_current.add(new_index)
                pairs.append((old_index, new_index, distance))

        remaining_original = [
            index for index in range(len(original)) if index not in matched_baseline
        ]
        remaining_observed = [
            index for index in range(len(observed)) if index not in matched_current
        ]
        remaining_pairs = sorted(
            (
                math.hypot(
                    original[old_index]["center_x"] - observed[new_index]["center_x"],
                    original[old_index]["center_y"] - observed[new_index]["center_y"],
                ),
                old_index,
                new_index,
            )
            for old_index in remaining_original
            for new_index in remaining_observed
        )
        for distance, old_index, new_index in remaining_pairs:
            if old_index in matched_baseline or new_index in matched_current:
                continue
            matched_baseline.add(old_index)
            matched_current.add(new_index)
            pairs.append((old_index, new_index, distance))

        for old_index, new_index, distance in pairs:
            old = original[old_index]
            new = observed[new_index]
            if distance <= MOVE_DISTANCE_THRESHOLD:
                continue
            x_bucket = round(new["center_x"] * 10)
            y_bucket = round(new["center_y"] * 10)
            key = (
                f"moved:{name}:{old['instance_number']}:{new['zone']}:"
                f"{x_bucket}:{y_bucket}"
            )
            candidates.append(
                {
                    "key": key,
                    "class_name": name,
                    "change_type": "moved",
                    "original_zone": old["zone"],
                    "current_zone": new["zone"],
                    "confidence": min(old["confidence"], new["confidence"]),
                }
            )

        for index, old in enumerate(original):
            if index in matched_baseline:
                continue
            instance = old["instance_number"]
            key = f"missing:{name}:{instance}"
            candidates.append(
                {
                    "key": key,
                    "class_name": name,
                    "change_type": "not_currently_visible",
                    "original_zone": old["zone"],
                    "current_zone": None,
                    "confidence": old["confidence"],
                }
            )
        new_counts = {}
        for index, new in enumerate(observed):
            if index in matched_current:
                continue
            zone = new["zone"]
            new_counts[zone] = new_counts.get(zone, 0) + 1
            instance = new_counts[zone]
            x_bucket = round(new["center_x"] * 10)
            y_bucket = round(new["center_y"] * 10)
            key = f"new:{name}:{zone}:{instance}:{x_bucket}:{y_bucket}"
            candidates.append(
                {
                    "key": key,
                    "class_name": name,
                    "change_type": "newly_observed",
                    "original_zone": None,
                    "current_zone": zone,
                    "confidence": new["confidence"],
                }
            )

    return candidates


def event_message(candidate):
    name = candidate["class_name"]
    change_type = candidate["change_type"]
    if change_type == "moved":
        original_zone = zone_label(candidate["original_zone"])
        current_zone = zone_label(candidate["current_zone"])
        if original_zone == current_zone:
            message = (
                f"A {name} appears to have shifted within the {current_zone} "
                "of the camera view."
            )
        else:
            message = (
                f"A {name} appears to have moved from {original_zone} to "
                f"{current_zone} in the camera view."
            )
        if candidate["current_zone"].startswith("lower-center") and name in {
            "chair",
            "dining table",
            "suitcase",
            "backpack",
            "handbag",
        }:
            message += (
                " It may be an obstacle. Please proceed carefully; the camera "
                "cannot confirm that a walkway is blocked."
            )
        return message
    if change_type == "not_currently_visible":
        return (
            f"The {name} usually seen in the "
            f"{zone_label(candidate['original_zone'])} is not currently visible. "
            "This does not confirm it was removed."
        )

    current_zone = zone_label(candidate["current_zone"])
    if candidate["current_zone"].startswith("lower-center") and name in {
        "chair",
        "dining table",
        "suitcase",
        "backpack",
        "handbag",
    }:
        return (
            f"A newly detected {name} is in the {current_zone} of the camera view. "
            "It may be an obstacle. Please proceed carefully; the camera cannot "
            "confirm that a walkway is blocked."
        )
    return f"A new {name} is visible in the {current_zone} of the camera view."


_MAX_MATCH_COST = 0.70
_UNMATCHED_COST = 0.36
_ASSIGNMENT_AMBIGUITY_MARGIN = 0.015
_MOVEMENT_THRESHOLD_MARGIN = 0.015
_INVALID_ASSIGNMENT_COST = 1_000_000.0


def _finite_number(value):
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def _validated_snapshot_detection(detection):
    if not isinstance(detection, dict):
        return None, None, "invalid_detection"
    name = detection.get("class_name")
    if not isinstance(name, str) or not name.strip():
        return None, None, "invalid_class_name"
    name = name.strip()
    if not is_monitored_class(name):
        return None, name, "unmonitored_class"

    toy_classes = {
        "teddy bear",
        "doll",
        "pink plush doll",
        "plush doll",
        "plush toy",
        "toy",
    }
    min_conf = (
        CANDIDATE_CONFIDENCE_THRESHOLD
        if name in toy_classes
        else CONFIDENCE_THRESHOLD
    )
    confidence = detection.get("confidence")
    if not _finite_number(confidence) or not min_conf <= confidence <= 1:
        return None, name, "unreliable_confidence"

    coordinates = [detection.get(key) for key in ("x1", "y1", "x2", "y2")]
    if not all(_finite_number(value) and 0 <= value <= 1 for value in coordinates):
        return None, name, "invalid_box"
    x1, y1, x2, y2 = (float(value) for value in coordinates)
    if x1 >= x2 or y1 >= y2:
        return None, name, "invalid_box"

    center_x = (x1 + x2) / 2
    center_y = (y1 + y2) / 2
    return (
        {
            **detection,
            "class_name": name,
            "confidence": float(confidence),
            "center_x": center_x,
            "center_y": center_y,
            "zone": image_zone(center_x, center_y),
        },
        name,
        None,
    )


def _box_iou(first, second):
    intersection_x1 = max(first["x1"], second["x1"])
    intersection_y1 = max(first["y1"], second["y1"])
    intersection_x2 = min(first["x2"], second["x2"])
    intersection_y2 = min(first["y2"], second["y2"])
    intersection = max(0.0, intersection_x2 - intersection_x1) * max(
        0.0, intersection_y2 - intersection_y1
    )
    first_area = (first["x2"] - first["x1"]) * (first["y2"] - first["y1"])
    second_area = (second["x2"] - second["x1"]) * (
        second["y2"] - second["y1"]
    )
    union = first_area + second_area - intersection
    return intersection / union if union > 0 else 0.0


def _matching_metrics(first, second):
    center_distance = math.hypot(
        first["center_x"] - second["center_x"],
        first["center_y"] - second["center_y"],
    )
    iou = _box_iou(first, second)
    first_width = first["x2"] - first["x1"]
    first_height = first["y2"] - first["y1"]
    second_width = second["x2"] - second["x1"]
    second_height = second["y2"] - second["y1"]
    size_difference = min(
        1.0,
        (
            abs(math.log(first_width / second_width))
            + abs(math.log(first_height / second_height))
        )
        / (2 * math.log(4)),
    )
    if size_difference > 0.85 and iou < 0.10:
        return None, center_distance, iou, size_difference

    normalized_distance = min(1.0, center_distance / math.sqrt(2))
    confidence_difference = abs(first["confidence"] - second["confidence"])
    cost = (
        0.45 * normalized_distance
        + 0.30 * (1 - iou)
        + 0.20 * size_difference
        + 0.05 * confidence_difference
    )
    if cost > _MAX_MATCH_COST:
        return None, center_distance, iou, size_difference
    return cost, center_distance, iou, size_difference


def _minimum_cost_assignment(costs):
    """Return a minimum-cost square assignment using the Hungarian algorithm."""
    size = len(costs)
    if size == 0:
        return [], 0.0

    row_potentials = [0.0] * (size + 1)
    column_potentials = [0.0] * (size + 1)
    matched_row = [0] * (size + 1)
    previous_column = [0] * (size + 1)

    for row in range(1, size + 1):
        matched_row[0] = row
        current_column = 0
        minimum_reduced_cost = [math.inf] * (size + 1)
        used_columns = [False] * (size + 1)
        while True:
            used_columns[current_column] = True
            current_row = matched_row[current_column]
            delta = math.inf
            next_column = 0
            for column in range(1, size + 1):
                if used_columns[column]:
                    continue
                reduced_cost = (
                    costs[current_row - 1][column - 1]
                    - row_potentials[current_row]
                    - column_potentials[column]
                )
                if reduced_cost < minimum_reduced_cost[column]:
                    minimum_reduced_cost[column] = reduced_cost
                    previous_column[column] = current_column
                if minimum_reduced_cost[column] < delta:
                    delta = minimum_reduced_cost[column]
                    next_column = column
            for column in range(size + 1):
                if used_columns[column]:
                    row_potentials[matched_row[column]] += delta
                    column_potentials[column] -= delta
                else:
                    minimum_reduced_cost[column] -= delta
            current_column = next_column
            if matched_row[current_column] == 0:
                break

        while True:
            next_column = previous_column[current_column]
            matched_row[current_column] = matched_row[next_column]
            current_column = next_column
            if current_column == 0:
                break

    assignment = [
        (matched_row[column] - 1, column - 1)
        for column in range(1, size + 1)
        if matched_row[column]
    ]
    total_cost = sum(costs[row][column] for row, column in assignment)
    return assignment, total_cost


def _box_record(detection):
    return {
        "x1": detection["x1"],
        "y1": detection["y1"],
        "x2": detection["x2"],
        "y2": detection["y2"],
    }


def _position_record(detection):
    return {
        "center_x": round(detection["center_x"], 3),
        "center_y": round(detection["center_y"], 3),
        "zone": detection["zone"],
    }


def _comparison_result(
    unchanged,
    moved,
    newly_visible,
    not_currently_visible,
    uncertain,
    total_baseline,
    total_current,
):
    return {
        "summary": {
            "unchanged": len(unchanged),
            "moved": len(moved),
            "new": len(newly_visible),
            "missing": len(not_currently_visible),
            "newly_visible": len(newly_visible),
            "not_currently_visible": len(not_currently_visible),
            "uncertain": len(uncertain),
            "total_baseline": total_baseline,
            "total_latest": total_current,
        },
        "unchanged": unchanged,
        "moved": moved,
        "newly_visible": newly_visible,
        "not_currently_visible": not_currently_visible,
        "uncertain": uncertain,
        # Keep the existing keys consumed by /api/comparison and other callers.
        "new": newly_visible,
        "missing": not_currently_visible,
    }


def categorize_room_comparison(
    baseline,
    current,
    before_frame=None,
    after_frame=None,
):
    """Compare two snapshots without forcing ambiguous detections into a match."""
    unchanged = []
    moved = []
    newly_visible = []
    not_currently_visible = []
    uncertain = []
    if not isinstance(baseline, (list, tuple)) or not isinstance(
        current, (list, tuple)
    ):
        uncertain.append({"class_name": None, "reason": "invalid_detection_set"})
        return _comparison_result(
            unchanged, moved, newly_visible, not_currently_visible, uncertain,
            len(baseline) if isinstance(baseline, (list, tuple)) else 0,
            len(current) if isinstance(current, (list, tuple)) else 0,
        )

    has_frames = (
        before_frame is not None
        and after_frame is not None
        and hasattr(before_frame, "shape")
        and hasattr(after_frame, "shape")
        and len(before_frame.shape) >= 2
        and len(after_frame.shape) >= 2
    )
    frame_width = before_frame.shape[1] if has_frames else 640
    frame_height = before_frame.shape[0] if has_frames else 480

    if not baseline or not current:
        if not baseline and not current:
            if has_frames:
                vis_diff = compute_overall_visual_change_ratio(
                    before_frame, after_frame
                )
                if vis_diff > 0.05:
                    uncertain.append(
                        {
                            "class_name": None,
                            "reason": "unclassified_visual_change",
                            "message": f"Significant visual difference ({round(vis_diff * 100, 1)}%) detected between BEFORE and AFTER.",
                            "visual_change_ratio": vis_diff,
                        }
                    )
            else:
                uncertain.append(
                    {
                        "class_name": None,
                        "side": "both",
                        "reason": "empty_detection_set",
                    }
                )
            return _comparison_result(
                unchanged,
                moved,
                newly_visible,
                not_currently_visible,
                uncertain,
                len(baseline),
                len(current),
            )

        if not baseline:
            # Baseline has 0 detections; current has detections
            if has_frames:
                for idx, det in enumerate(current):
                    is_new, _ = verify_object_visibility_change(
                        det,
                        after_frame,
                        before_frame,
                        frame_width,
                        frame_height,
                    )
                    if is_new:
                        newly_visible.append(
                            {
                                "class_name": det["class_name"],
                                "instance_number": det.get(
                                    "instance_number", idx + 1
                                ),
                                "zone": det["zone"],
                                "confidence": det["confidence"],
                                "current_box": _box_record(det),
                                "visually_confirmed": True,
                            }
                        )
                    else:
                        uncertain.append(
                            {
                                "class_name": det["class_name"],
                                "side": "before",
                                "reason": "potential_detector_miss",
                                "current_box": _box_record(det),
                            }
                        )
            else:
                uncertain.append(
                    {
                        "class_name": None,
                        "side": "before",
                        "reason": "empty_detection_set",
                    }
                )
            return _comparison_result(
                unchanged,
                moved,
                newly_visible,
                not_currently_visible,
                uncertain,
                len(baseline),
                len(current),
            )

        if not current:
            # Current has 0 detections; baseline has detections
            if has_frames:
                for idx, det in enumerate(baseline):
                    is_missing, _ = verify_object_visibility_change(
                        det,
                        before_frame,
                        after_frame,
                        frame_width,
                        frame_height,
                    )
                    if is_missing:
                        not_currently_visible.append(
                            {
                                "class_name": det["class_name"],
                                "instance_number": det.get(
                                    "instance_number", idx + 1
                                ),
                                "zone": det["zone"],
                                "confidence": det["confidence"],
                                "baseline_box": _box_record(det),
                                "visually_confirmed": True,
                            }
                        )
                    else:
                        uncertain.append(
                            {
                                "class_name": det["class_name"],
                                "side": "after",
                                "reason": "potential_detector_miss",
                                "baseline_box": _box_record(det),
                            }
                        )
            else:
                uncertain.append(
                    {
                        "class_name": None,
                        "side": "after",
                        "reason": "empty_detection_set",
                    }
                )
            return _comparison_result(
                unchanged,
                moved,
                newly_visible,
                not_currently_visible,
                uncertain,
                len(baseline),
                len(current),
            )

    valid_by_side = {"before": {}, "after": {}}
    invalid_classes = {"before": set(), "after": set()}
    for side, records in (("before", baseline), ("after", current)):
        for index, detection in enumerate(records):
            normalized, name, reason = _validated_snapshot_detection(detection)
            if reason:
                if reason == "unmonitored_class":
                    # Non-monitored classes (e.g. background tableware or misclassified cords) are ignored
                    continue
                uncertain.append(
                    {
                        "class_name": name,
                        "side": side,
                        "index": index,
                        "reason": reason,
                    }
                )
                if name:
                    invalid_classes[side].add(name)
                continue
            valid_by_side[side].setdefault(name, []).append(normalized)

    names = sorted(
        set(valid_by_side["before"])
        | set(valid_by_side["after"])
        | invalid_classes["before"]
        | invalid_classes["after"]
    )
    for name in names:
        if name in invalid_classes["before"] or name in invalid_classes["after"]:
            uncertain.append(
                {"class_name": name, "reason": "class_contains_invalid_detection"}
            )
            continue

        original = sorted(
            valid_by_side["before"].get(name, []),
            key=lambda item: (
                item.get("instance_number", 0),
                item["center_y"],
                item["center_x"],
            ),
        )
        observed = sorted(
            valid_by_side["after"].get(name, []),
            key=lambda item: (item["center_y"], item["center_x"]),
        )
        old_count = len(original)
        new_count = len(observed)
        if not old_count:
            for index, detection in enumerate(observed):
                newly_visible.append(
                    {
                        "class_name": name,
                        "instance_number": detection.get("instance_number", index + 1),
                        "zone": detection["zone"],
                        "confidence": detection["confidence"],
                        "current_box": _box_record(detection),
                    }
                )
            continue
        if not new_count:
            for index, detection in enumerate(original):
                not_currently_visible.append(
                    {
                        "class_name": name,
                        "instance_number": detection.get("instance_number", index + 1),
                        "zone": detection["zone"],
                        "confidence": detection["confidence"],
                        "baseline_box": _box_record(detection),
                    }
                )
            continue

        matrix_size = old_count + new_count
        costs = [[0.0] * matrix_size for _ in range(matrix_size)]
        metrics = {}
        for old_index, old in enumerate(original):
            for new_index, new_item in enumerate(observed):
                cost, distance, iou, size_difference = _matching_metrics(old, new_item)
                metrics[(old_index, new_index)] = (
                    cost,
                    distance,
                    iou,
                    size_difference,
                )
                costs[old_index][new_index] = (
                    cost if cost is not None else _INVALID_ASSIGNMENT_COST
                )
            for dummy_column in range(new_count, matrix_size):
                costs[old_index][dummy_column] = _UNMATCHED_COST
        for dummy_row in range(old_count, matrix_size):
            for new_index in range(new_count):
                costs[dummy_row][new_index] = _UNMATCHED_COST

        assignment, best_total_cost = _minimum_cost_assignment(costs)
        pairs = {
            (old_index, new_index)
            for old_index, new_index in assignment
            if old_index < old_count
            and new_index < new_count
            and metrics[(old_index, new_index)][0] is not None
        }

        ambiguous_old = set()
        ambiguous_new = set()
        for old_index, new_index in pairs:
            alternate_costs = [row[:] for row in costs]
            alternate_costs[old_index][new_index] = _INVALID_ASSIGNMENT_COST
            alternate_assignment, alternate_total_cost = _minimum_cost_assignment(
                alternate_costs
            )
            if alternate_total_cost - best_total_cost > _ASSIGNMENT_AMBIGUITY_MARGIN:
                continue
            alternate_pairs = {
                (row, column)
                for row, column in alternate_assignment
                if row < old_count
                and column < new_count
                and metrics[(row, column)][0] is not None
            }
            for changed_old, changed_new in pairs.symmetric_difference(alternate_pairs):
                ambiguous_old.add(changed_old)
                ambiguous_new.add(changed_new)

        for index in sorted(ambiguous_old):
            uncertain.append(
                {
                    "class_name": name,
                    "side": "before",
                    "reason": "ambiguous_assignment",
                    "previous_position": _position_record(original[index]),
                    "baseline_box": _box_record(original[index]),
                }
            )
        for index in sorted(ambiguous_new):
            uncertain.append(
                {
                    "class_name": name,
                    "side": "after",
                    "reason": "ambiguous_assignment",
                    "current_position": _position_record(observed[index]),
                    "current_box": _box_record(observed[index]),
                }
            )

        matched_old = {old_index for old_index, _ in pairs}
        matched_new = {new_index for _, new_index in pairs}
        for old_index, new_index in sorted(pairs):
            if old_index in ambiguous_old or new_index in ambiguous_new:
                continue
            old = original[old_index]
            new_item = observed[new_index]
            _, distance, _, _ = metrics[(old_index, new_index)]
            if abs(distance - MOVE_DISTANCE_THRESHOLD) <= _MOVEMENT_THRESHOLD_MARGIN:
                uncertain.append(
                    {
                        "class_name": name,
                        "reason": "movement_threshold_ambiguous",
                        "previous_position": _position_record(old),
                        "current_position": _position_record(new_item),
                        "baseline_box": _box_record(old),
                        "current_box": _box_record(new_item),
                    }
                )
                continue

            match = {
                "class_name": name,
                "instance_number": old.get("instance_number", old_index + 1),
                "confidence": min(old["confidence"], new_item["confidence"]),
                "distance": round(distance, 3),
                "baseline_box": _box_record(old),
                "current_box": _box_record(new_item),
            }
            if distance > MOVE_DISTANCE_THRESHOLD:
                moved.append(
                    {
                        **match,
                        "original_zone": old["zone"],
                        "current_zone": new_item["zone"],
                        "previous_position": _position_record(old),
                        "current_position": _position_record(new_item),
                    }
                )
            else:
                unchanged.append(
                    {
                        **match,
                        "zone": old["zone"],
                        "current_zone": new_item["zone"],
                    }
                )

        remaining_old = [
            index
            for index in range(old_count)
            if index not in matched_old and index not in ambiguous_old
        ]
        remaining_new = [
            index
            for index in range(new_count)
            if index not in matched_new and index not in ambiguous_new
        ]
        while remaining_old and remaining_new:
            old_index, new_index = min(
                (
                    (
                        metrics[(old_index, new_index)][1],
                        old_index,
                        new_index,
                    )
                    for old_index in remaining_old
                    for new_index in remaining_new
                )
            )[1:]
            uncertain.append(
                {
                    "class_name": name,
                    "reason": "match_cost_exceeded",
                    "previous_position": _position_record(original[old_index]),
                    "current_position": _position_record(observed[new_index]),
                    "baseline_box": _box_record(original[old_index]),
                    "current_box": _box_record(observed[new_index]),
                }
            )
            remaining_old.remove(old_index)
            remaining_new.remove(new_index)

        for index in remaining_old:
            detection = original[index]
            if has_frames:
                is_missing, _ = verify_object_visibility_change(
                    detection, before_frame, after_frame, frame_width, frame_height
                )
                if not is_missing:
                    # Region in after_frame is visually unchanged -> detector miss!
                    uncertain.append(
                        {
                            "class_name": name,
                            "side": "after",
                            "reason": "potential_detector_miss",
                            "baseline_box": _box_record(detection),
                        }
                    )
                    continue

            not_currently_visible.append(
                {
                    "class_name": name,
                    "instance_number": detection.get("instance_number", index + 1),
                    "zone": detection["zone"],
                    "confidence": detection["confidence"],
                    "baseline_box": _box_record(detection),
                    "visually_confirmed": True if has_frames else False,
                }
            )

        for index in remaining_new:
            detection = observed[index]
            if has_frames:
                is_new, _ = verify_object_visibility_change(
                    detection, after_frame, before_frame, frame_width, frame_height
                )
                if not is_new:
                    # Region in before_frame is visually unchanged -> detector miss on baseline!
                    uncertain.append(
                        {
                            "class_name": name,
                            "side": "before",
                            "reason": "potential_detector_miss",
                            "current_box": _box_record(detection),
                        }
                    )
                    continue

            newly_visible.append(
                {
                    "class_name": name,
                    "instance_number": detection.get("instance_number", index + 1),
                    "zone": detection["zone"],
                    "confidence": detection["confidence"],
                    "current_box": _box_record(detection),
                    "visually_confirmed": True if has_frames else False,
                }
            )

    # Scene-level visual sanity check: if no objects changed, but frame difference is high
    if (
        has_frames
        and len(moved) == 0
        and len(newly_visible) == 0
        and len(not_currently_visible) == 0
    ):
        overall_diff = compute_overall_visual_change_ratio(
            before_frame, after_frame
        )
        if overall_diff > 0.05:
            uncertain.append(
                {
                    "class_name": None,
                    "reason": "unclassified_visual_change",
                    "message": f"Significant scene visual difference ({round(overall_diff * 100, 1)}%) detected between BEFORE and AFTER.",
                    "visual_change_ratio": overall_diff,
                }
            )

    return _comparison_result(
        unchanged,
        moved,
        newly_visible,
        not_currently_visible,
        uncertain,
        len(baseline),
        len(current),
    )

