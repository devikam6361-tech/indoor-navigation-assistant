# Indoor Object Dataset Specification

**Phase:** P6-1 — Custom Indoor Object Dataset Development  
**Status:** Proposed specification for review  
**Scope:** Detection labels for indoor navigation and room-change monitoring

## 1. Existing project setup reviewed

- [ai/config.py](./ai/config.py) points production inference at the repository-root
  [yolo11n.pt](./yolo11n.pt) and sets `CONFIDENCE_THRESHOLD` to `0.25`.
- The production detector in [ai/services/yolo_service.py](./ai/services/yolo_service.py) loads the configured
  model and retains detections only when their normalized class name is in
  `SUPPORTED_CLASSES`.
- `SUPPORTED_CLASSES` currently contains 28 COCO names. `MONITORED_CLASSES`
  contains 10 of those names and is a narrower application-level set.
- The production model call does not explicitly set image size, IoU, or device.
  The existing [curated evaluation script](./ai/evaluate_curated_indoor.py)
  separately names [yolo11n.pt](./yolo11n.pt) and
  [yolo11s.pt](./yolo11s.pt) and uses image size 640, confidence 0.25, IoU 0.7,
  and CPU inference.
- [model_capabilities.yaml](./model_capabilities.yaml) is an optional agent/model capability registry. It
  does not configure YOLO, define object labels, or define class IDs.
- This specification does not change model weights, runtime configuration, or
  either application-level class filter. In particular, adding a dataset class
  does not by itself make production retain or monitor that class.

## 2. Label and class-ID contract

The following IDs are the fixed proposed order for this dataset. Class names
must remain unchanged and IDs must not be re-used or reordered after annotation
begins. A future taxonomy change requires a new dataset version.

“COCO pretrained” means the label exists in the standard COCO label set used by
the current YOLO11 pretrained weights. A related label is not necessarily an
exact semantic match. “Current supported” and “current monitored” describe the
existing application filters, not the model's underlying COCO capability.

| ID | Dataset class name | COCO pretrained | Current supported | Current monitored | Annotation rule | Target instances |
|---:|---|---|---|---|---|---:|
| 0 | `person` | Yes | No | No | One box per real person. Include visible body parts; exclude people shown only in photographs, posters, screens, or reflections. | 1,500 |
| 1 | `chair` | Yes | Yes | Yes | One box per individual chair, including dining, office, and armchairs. Do not label benches, stools, or sofas as chairs. | 1,500 |
| 2 | `couch` | Yes | Yes | Yes | One box for each sofa or loveseat, including its attached frame and cushions. Do not box loose cushions separately. | 1,500 |
| 3 | `bed` | Yes | Yes | No | One box for each bed, covering the visible frame and mattress. Bedding and pillows are not separate targets. | 1,500 |
| 4 | `table` | No — related COCO label: `dining table` | No — current filter has `dining table`, not this broader class | No | One box per freestanding dining, coffee, side, or end table, including its supporting structure. Do not label counters, desks, shelves, or cabinets as tables. | 2,000 |
| 5 | `door` | No | No | No | One box per doorway assembly, enclosing the visible frame and door leaf or leaves. Include open doors; do not label a bare wall opening with no identifiable frame or door. | 2,000 |
| 6 | `stairs` | No | No | No | One box per continuous flight of steps, enclosing visible treads/risers and attached handrails. Separate flights divided by a landing when they are distinct. | 2,000 |
| 7 | `cabinet` | No | No | No | One box per distinct cabinet or continuous built-in cabinet bank. Do not label each cabinet door, drawer, or handle separately. | 2,000 |
| 8 | `refrigerator` | Yes | Yes | No | One box for the complete refrigerator/freezer appliance, including attached doors and handles. Do not include surrounding cabinetry. | 1,500 |
| 9 | `microwave` | Yes | Yes | No | One box around the microwave appliance only, whether freestanding or built in. | 1,500 |
| 10 | `sink` | Yes | Yes | No | One box around the sink basin and fixed rim. Exclude surrounding counter and cabinets; do not label a bathtub or shower as a sink. | 1,500 |
| 11 | `toilet` | Yes | Yes | No | One box per toilet fixture, including its visible tank and bowl. Do not include nearby walls or bathroom fixtures. | 1,500 |
| 12 | `potted plant` | Yes | Yes | Yes | One box per plant together with its pot. Do not label cut flowers, printed plant images, or an unpotted outdoor tree. | 1,500 |
| 13 | `backpack` | Yes | Yes | Yes | One box per identifiable backpack, whether carried, hung, stored, or on the floor. Do not label a handbag or suitcase as a backpack. | 1,500 |
| 14 | `handbag` | Yes | Yes | Yes | One box per identifiable handbag or purse. Do not label backpacks, shopping bags, or suitcases as handbags. | 1,500 |
| 15 | `suitcase` | Yes | Yes | Yes | One box per identifiable travel suitcase, whether upright, open, carried, or on the floor. Do not label generic cartons as suitcases. | 1,500 |
| 16 | `bottle` | Yes | Yes | Yes | One box per visible bottle, including plastic or glass bottles. Do not label cups, bowls, jars, or vases as bottles. | 1,500 |
| 17 | `footwear` | No | No | No | One box per individual shoe, boot, or slipper. Label left and right shoes separately when both are visible; do not combine a pair into one box. | 2,000 |
| 18 | `box` | No | No | No | One box per distinct rigid cardboard or storage box. Exclude furniture, appliances, bags, and decorative open containers. | 2,000 |
| 19 | `cable` | No | No | No | One box per continuous, identifiable loose power or charging cable lying across a walkable surface. Do not label installed wiring or split one cable into multiple boxes. | 2,000 |

The proposed set therefore contains **13 COCO-backed classes** and **7 classes
requiring custom labeled examples**: `table`, `door`, `stairs`, `cabinet`,
`footwear`, `box`, and `cable`. Although COCO includes `dining table`, the
proposed `table` class deliberately covers several table types and therefore
requires custom training data for consistent coverage.

The COCO-backed classes are available to the pretrained weights, but the
existing application filter still excludes `person`. The proposed custom
classes are not in the existing application filters. No filter or production
configuration changes are part of P6-1.

## 3. Annotation format and general rules

- Use axis-aligned bounding boxes and the standard YOLO detection row format:
  `class_id x_center y_center width height`.
- Coordinates must be normalized to the image dimensions, lie in `[0, 1]`, and
  use the class IDs in this specification.
- Draw a tight box around the visible extent of the object. Do not include
  unrelated floor, wall, or neighboring objects to make boxes easier to draw.
- Annotate each distinct, identifiable instance of one of the 20 target classes.
  Do not add a generic “obstacle” class or infer an object that is not visible.
- Use the class definitions above consistently. If an object's identity is
  ambiguous, do not guess; flag the image for review.
- COCO class IDs are not reused. The dataset's own IDs 0–19 are authoritative
  for this taxonomy, including when pretrained weights are used for fine-tuning.

## 4. Partial visibility, overlap, multiplicity, and occlusion

- **Partially visible at image edge:** Annotate when the visible portion is
  identifiable and at least approximately 20% of the object is visible. Draw
  the box only to the image boundary around visible pixels; never extrapolate a
  box beyond the image.
- **Occluded:** Annotate an object when at least approximately 20% is visible
  and its class can still be identified. Box its visible extent. If less is
  visible or identity is uncertain, flag the image for review rather than
  creating a speculative label.
- **Unlabelable target in an otherwise usable image:** Standard YOLO detection
  labels do not encode ignored regions. If a target is clearly present but
  cannot be labeled consistently, exclude that image from training or resolve
  it during review; do not silently treat the known target as background.
- **Multiple instances:** Use one box per instance, even when instances touch.
  For example, label each chair separately and label the table separately.
- **Overlapping objects:** Label each identifiable object once. Boxes may
  overlap when the physical objects overlap in the image (for example, a person
  carrying a backpack). Do not merge them into one box.
- **Repeated parts or groups:** Do not create separate labels for components
  that the class rule defines as one object (for example, a bed and its pillows,
  a potted plant and its pot, or a cabinet bank and its doors).
- **Thin cables:** Enclose the continuous visible cable path in one tight
  rectangle. Do not annotate separate fragments of the same cable as separate
  instances.

## 5. Duplicate and consistency controls

1. Assign each capture a stable source, room, and session identifier before
   splitting or annotation.
2. Annotate each physical instance once per image. Do not duplicate boxes to
   represent different parts, viewpoints, or levels of occlusion.
3. Use only one class per instance. Apply the class-specific definitions above
   to distinguish similar objects; do not label one object as both a generic
   and a specific class.
4. Permit overlap only where two distinct objects visibly overlap. Do not place
   duplicate boxes around the same object or use a loose group box around
   adjacent instances.
5. Run a second-person review for all custom classes and ambiguous cases.
   Review boxes for class ID, duplicate instances, tightness, and normalized
   coordinate validity.
6. Keep reviewed annotation exports immutable and version them with the
   dataset. Any correction must update the source annotation and retain an
   auditable dataset version.

## 6. Dataset split and leakage prevention

Target a **70% train / 20% validation / 10% test** split. Apply the split to
capture groups, not individual frames:

- Keep all images from the same physical room in a single split, even if they
  were captured in different sessions.
- Keep every frame from the same capture session, burst, or video in one split.
- If room and session groups intersect, assign the entire connected group to
  one split so no linked room/session appears in multiple splits.
- Do not place near-identical frames, crops, resized copies, or alternate
  exports of an image across splits. Use exact and visual near-duplicate checks.
- Assign groups to approximate the 70:20:10 ratio while balancing class and
  scene coverage. Do not break room/session boundaries to force exact counts.
- Keep the test split fixed and untouched during annotation-rule changes and
  model selection. Use validation for iteration; report final results on test.

## 7. Collection targets

Targets in the class table are **labeled object instances**, not image counts.
They are initial collection goals; images should include different rooms,
viewpoints, object sizes, lighting, backgrounds, and visibility conditions.
Avoid meeting a target mainly with repeated frames of the same physical object.

The targets sum to approximately **33,500 labeled instances**: 13 COCO-backed
classes at 1,500 each and 7 custom classes at 2,000 each. Custom targets are
higher to provide sufficient examples for classes absent from COCO. Preserve
the grouped 70:20:10 split when distributing these examples.

## 8. Recommended folder layout

Keep the future dataset separate from existing source images, model weights,
and evaluation outputs:

```text
datasets/
└── indoor_navigation_v1/
    ├── data.yaml
    ├── images/
    │   ├── train/
    │   ├── val/
    │   └── test/
    ├── labels/
    │   ├── train/
    │   ├── val/
    │   └── test/
    └── metadata/
        ├── capture_manifest.csv
        └── annotation_guidelines.md
```

`capture_manifest.csv` should record image filename, source/license, room ID,
session ID, split, and relevant capture conditions. The dataset YAML must map
the stable IDs to the exact class names and paths in this specification. Store
the annotation guideline and dataset version with the data; do not use
evaluation images as training data when they are reserved for a held-out test.

## 9. P6-1 boundary

This document defines the proposed dataset taxonomy and collection/annotation
plan only. It does not collect or download images, create dataset folders,
change application filters, modify model weights or configuration, or train a
model. P6-2 should begin only after approval of this specification.
