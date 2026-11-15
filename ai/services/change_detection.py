import math

from config import MONITORED_CLASSES, MOVE_DISTANCE_THRESHOLD, SUPPORTED_CLASSES
from utils.formatting import event_response, zone_label


def compare_detections(baseline, current):
    candidates = []
    classes = {
        item["class_name"]
        for item in baseline + current
        if item["class_name"] in MONITORED_CLASSES
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


def categorize_room_comparison(baseline, current):
    """
    Compares baseline detections with current/latest detections and returns
    a comprehensive 4-category breakdown:
      - unchanged: objects whose position remained within MOVE_DISTANCE_THRESHOLD
      - moved: objects that moved beyond MOVE_DISTANCE_THRESHOLD (with previous & current positions)
      - missing: baseline objects not observed in current scan
      - new: current objects that were not present in the baseline

    Correctly resolves multiple objects of the same class using two-phase
    greedy nearest-neighbor distance matching.
    """
    unchanged = []
    moved = []
    missing = []
    new = []

    classes = {
        item["class_name"]
        for item in baseline + current
        if item.get("class_name") in SUPPORTED_CLASSES or item.get("class_name") in MONITORED_CLASSES
    }

    for name in sorted(classes):
        matched_baseline = set()
        matched_current = set()
        original = sorted(
            (item for item in baseline if item.get("class_name") == name),
            key=lambda item: item.get("instance_number", 0),
        )
        observed = sorted(
            (item for item in current if item.get("class_name") == name),
            key=lambda item: (item.get("center_y", 0), item.get("center_x", 0)),
        )

        distances = sorted(
            (
                math.hypot(
                    old["center_x"] - new_item["center_x"],
                    old["center_y"] - new_item["center_y"],
                ),
                old_index,
                new_index,
            )
            for old_index, old in enumerate(original)
            for new_index, new_item in enumerate(observed)
        )

        # Pass 1: Match stationary objects (distance <= MOVE_DISTANCE_THRESHOLD)
        for distance, old_index, new_index in distances:
            if old_index in matched_baseline or new_index in matched_current:
                continue
            if distance <= MOVE_DISTANCE_THRESHOLD:
                matched_baseline.add(old_index)
                matched_current.add(new_index)
                old = original[old_index]
                cur = observed[new_index]
                unchanged.append({
                    "class_name": name,
                    "instance_number": old.get("instance_number", old_index + 1),
                    "zone": old["zone"],
                    "current_zone": cur["zone"],
                    "confidence": cur.get("confidence", old.get("confidence", 1.0)),
                    "distance": round(distance, 3),
                    "baseline_box": {
                        "x1": old.get("x1"), "y1": old.get("y1"),
                        "x2": old.get("x2"), "y2": old.get("y2"),
                    },
                    "current_box": {
                        "x1": cur.get("x1"), "y1": cur.get("y1"),
                        "x2": cur.get("x2"), "y2": cur.get("y2"),
                    },
                })

        # Pass 2: Match moved objects from remaining unmatched candidates
        remaining_original = [i for i in range(len(original)) if i not in matched_baseline]
        remaining_observed = [i for i in range(len(observed)) if i not in matched_current]
        remaining_distances = sorted(
            (
                math.hypot(
                    original[old_idx]["center_x"] - observed[new_idx]["center_x"],
                    original[old_idx]["center_y"] - observed[new_idx]["center_y"],
                ),
                old_idx,
                new_idx,
            )
            for old_idx in remaining_original
            for new_idx in remaining_observed
        )

        for distance, old_index, new_index in remaining_distances:
            if old_index in matched_baseline or new_index in matched_current:
                continue
            matched_baseline.add(old_index)
            matched_current.add(new_index)
            old = original[old_index]
            cur = observed[new_index]
            moved.append({
                "class_name": name,
                "instance_number": old.get("instance_number", old_index + 1),
                "original_zone": old["zone"],
                "current_zone": cur["zone"],
                "confidence": min(old.get("confidence", 1.0), cur.get("confidence", 1.0)),
                "distance": round(distance, 3),
                "previous_position": {
                    "center_x": round(old["center_x"], 3),
                    "center_y": round(old["center_y"], 3),
                    "zone": old["zone"],
                },
                "current_position": {
                    "center_x": round(cur["center_x"], 3),
                    "center_y": round(cur["center_y"], 3),
                    "zone": cur["zone"],
                },
                "baseline_box": {
                    "x1": old.get("x1"), "y1": old.get("y1"),
                    "x2": old.get("x2"), "y2": old.get("y2"),
                },
                "current_box": {
                    "x1": cur.get("x1"), "y1": cur.get("y1"),
                    "x2": cur.get("x2"), "y2": cur.get("y2"),
                },
            })

        # Pass 3: Unmatched baseline items are Missing
        for old_index, old in enumerate(original):
            if old_index in matched_baseline:
                continue
            missing.append({
                "class_name": name,
                "instance_number": old.get("instance_number", old_index + 1),
                "zone": old["zone"],
                "confidence": old.get("confidence", 1.0),
                "baseline_box": {
                    "x1": old.get("x1"), "y1": old.get("y1"),
                    "x2": old.get("x2"), "y2": old.get("y2"),
                },
            })

        # Pass 4: Unmatched current items are New
        for new_index, cur in enumerate(observed):
            if new_index in matched_current:
                continue
            new.append({
                "class_name": name,
                "instance_number": cur.get("instance_number", new_index + 1),
                "zone": cur["zone"],
                "confidence": cur.get("confidence", 1.0),
                "current_box": {
                    "x1": cur.get("x1"), "y1": cur.get("y1"),
                    "x2": cur.get("x2"), "y2": cur.get("y2"),
                },
            })

    return {
        "summary": {
            "unchanged": len(unchanged),
            "moved": len(moved),
            "new": len(new),
            "missing": len(missing),
            "total_baseline": len(baseline),
            "total_latest": len(current),
        },
        "unchanged": unchanged,
        "moved": moved,
        "new": new,
        "missing": missing,
    }

