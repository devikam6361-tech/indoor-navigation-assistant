# Indoor Dataset Source Research

**Phase:** P6-2 — Indoor Dataset Source Research  
**Basis:** Approved [P6-1 dataset specification](./INDOOR_DATASET_SPECIFICATION.md)  
**Scope:** Public-source research only; no images or datasets were downloaded.

## Executive summary

No single source is both an indoor-only dataset and a license-cleared, ready-to-use
YOLO dataset for all 20 specified classes.

Recommended source strategy:

1. Use **Open Images V7** as the broadest candidate for existing box annotations:
   its boxable taxonomy includes direct or close labels for most specified
   classes, including door, stairs, cabinetry, footwear, and box. It has no
   dedicated boxable cable class. Its broad web-image mix requires indoor-scene
   filtering and per-image rights verification.
2. Use **COCO 2017** as a source of examples for the 13 COCO-backed classes in
   P6-1. It is not a source for the seven custom classes, and its “dining table”
   label is narrower than this project's `table` class.
3. Use **project-captured, consented indoor images** to fill the cable gap and
   add representative indoor views for every class. This is the most direct
   route to consistent class definitions and controlled rights.
4. Treat **ADE20K, SUN RGB-D, and ScanNet** as supplemental indoor sources only
   after confirming their current terms and mapping their annotations. They are
   not plug-and-play YOLO box datasets.
5. **Objects365 is not recommended for commercial training** under its stated
   academic-purpose restriction.

“Free to access” does not guarantee permission for commercial use, redistribution,
or derivative datasets. Before retaining any third-party image, preserve its
source, license, attribution, and permission status in the capture manifest. This
research is not legal advice.

## Source-by-source assessment

### 1. Open Images V7

- **Available classes:** The 600 boxable labels include `Person`, `Chair`,
  `Couch`, `Bed`, `Table`, `Coffee table`, `Kitchen & dining room table`,
  `Door`, `Stairs`, `Cabinetry`, `Refrigerator`, `Microwave oven`, `Sink`,
  `Toilet`, `Houseplant`, `Backpack`, `Handbag`, `Suitcase`, `Bottle`,
  `Footwear`, and `Box`. These are direct or close mappings to 19 of the
  specification's 20 classes. The taxonomy has no dedicated `cable` box class.
- **Approximate image count:** About 9.18 million images overall. Dense box
  annotations cover about 1.74 million training images, 41,620 validation
  images, and 125,436 test images (about 1.91 million total). The remainder
  should not be assumed to have object boxes.
- **Annotation format and quality:** CSV boxes with image ID, class ID, and
  normalized coordinates. Box rows also include flags for occlusion,
  truncation, group-of, depiction, and inside-object views. The project reports
  14.6 million training boxes over 600 classes; most were manually drawn, and
  the semi-automated portion was human-verified. Validation/test boxes were
  manually drawn. This is the strongest candidate for pre-annotated custom-class
  examples, but map Open Images labels to the P6-1 definitions carefully (for
  example, `Cabinetry` to `cabinet` and its several table labels to `table`).
- **License and commercial use:** The official page lists images as CC BY 2.0
  and annotations as CC BY 4.0, but explicitly disclaims warranties about each
  image's license and directs users to verify image rights. Commercial use is
  conditional on the actual image license, attribution, and other applicable
  rights; do not treat the whole URL collection as automatically cleared.
- **YOLO fine-tuning:** **Suitable after filtering and conversion.** Convert
  normalized XYXY CSV boxes to YOLO normalized center/width/height labels. Use
  the source flags to exclude depictions and group boxes if they conflict with
  P6-1 rules; review occlusion/truncation handling. Filter for actual indoor
  scenes and fill the `cable` gap with project captures.

### 2. COCO 2017

- **Available classes:** Exact P6-1 COCO-backed labels: `person`, `chair`,
  `couch`, `bed`, `refrigerator`, `microwave`, `sink`, `toilet`, `potted
  plant`, `backpack`, `handbag`, `suitcase`, and `bottle`. COCO's `dining
  table` can seed the broader custom `table` class but does not cover all
  coffee, side, and end tables. COCO has no exact labels for the other six
  custom classes.
- **Approximate image count:** COCO 2017 has about 118,000 training images,
  5,000 validation images, and about 41,000 test images. Test annotations are
  not generally available for local supervised training.
- **Annotation format and quality:** Instance annotations in JSON, including
  bounding boxes and segmentation polygons/masks for 80 categories. The
  instance boxes can be converted to YOLO format. Images are general-purpose
  web photos, not an indoor-only collection; individual target classes and
  indoor examples are a subset.
- **License and commercial use:** Follow the current [COCO terms of use](https://cocodataset.org/#termsofuse)
  and the source-image license/attribution requirements. Because COCO images
  originate from Flickr, verify the rights of each image intended for commercial
  training or redistribution rather than assuming that the annotations grant
  unrestricted image rights.
- **YOLO fine-tuning:** **Suitable for the COCO-backed subset.** Convert the
  JSON boxes and remap them to the fixed P6-1 IDs. Do not use COCO `dining
  table` as if it exhaustively labeled every table type in the custom `table`
  class.

### 3. Project-captured indoor images

- **Available classes:** All 20 P6-1 classes can be collected and labeled using
  the approved definitions, especially `cable`, which lacks a dedicated
  Open Images box class.
- **Approximate image count:** No new capture count is established by this
  research. The P6-1 per-class targets are instance counts, not image counts.
  The number of images will depend on room layouts and the number of visible
  instances.
- **Annotation format and quality:** Capture original indoor photos or video
  frames, then annotate directly to the P6-1 YOLO format. First-party annotation
  can enforce consistent boundaries, occlusion rules, and complete labels for
  all target classes in an image.
- **License and commercial use:** Best rights control when the project owns or
  has documented permission to use the images. Obtain participant consent and
  any required property permission; avoid or redact identifying personal
  information. Record the grant and restrictions in the manifest.
- **YOLO fine-tuning:** **Strongly suitable and necessary for gaps.** It is the
  recommended source for cables and for indoor-specific examples of the custom
  classes. Capture varied rooms, distances, lighting, floor placement, and
  occlusion; keep rooms and sessions grouped during the 70:20:10 split.

### 4. ADE20K

- **Available classes:** Indoor and outdoor scenes with broad object, part, and
  scene labels. Its 3,688-category vocabulary is useful for indoor context and
  may contain labels corresponding to furniture, fixtures, doors, stairs, and
  cabinets. Confirm the exact class inventory and instance-level availability
  before counting any target class.
- **Approximate image count:** 27,574 images in the current repository
  description: 25,574 training and 2,000 test images, across 365 scene types.
- **Annotation format and quality:** Pixel/instance segmentation maps,
  polygons, object-part labels, and per-image JSON metadata. This is rich scene
  annotation, but not a ready-made set of P6-1 YOLO boxes. Derive boxes from
  masks/polygons only where the object instance is clearly separable; review
  boundaries and class mapping.
- **License and commercial use:** Access requires sign-in and the dataset's
  [Terms of Use](https://ade20k.csail.mit.edu/terms). Commercial rights were
  not established from the accessible terms in this research; treat it as
  restricted until access is approved and the terms explicitly permit the
  intended use.
- **YOLO fine-tuning:** **Conditionally suitable as a supplemental source.**
  Useful for indoor scenes and custom-category candidates after terms review,
  conversion, and manual QA. Do not assume its segmentation labels cover all
  20 classes or match P6-1 definitions.

### 5. SUN RGB-D

- **Available classes:** Indoor RGB-D scenes with common furniture and room
  objects, including categories such as chairs, beds, sofas, tables, cabinets,
  and bathroom fixtures. It is potentially useful for indoor context and
  selected P6-1 objects; verify the exact class list and label coverage before
  mapping.
- **Approximate image count:** About 10,335 RGB-D images.
- **Annotation format and quality:** The dataset provides 2D and 3D object
  boxes, scene/layout information, and depth data. The 2D boxes are convertible
  to YOLO format, but the taxonomy and box conventions should be reviewed
  against P6-1, and not every target class is represented.
- **License and commercial use:** The dataset is research-oriented and includes
  data from multiple source datasets. The applicable terms and image-level
  rights must be checked before use; no blanket commercial clearance is
  established here. Do not use commercially without explicit permission.
- **YOLO fine-tuning:** **Conditionally suitable** for indoor-only examples
  after rights review, class mapping, and split-by-room/source controls. It is
  not a source for assuming coverage of cables, footwear, or every custom class.

### 6. ScanNet

- **Available classes:** Indoor RGB-D scans with instance-level semantic labels
  for common furniture and fixtures, including classes such as chair, couch,
  bed, table, cabinet, door, refrigerator, sink, and toilet. It is useful for
  indoor geometry and room context, but does not provide the full P6-1
  taxonomy; verify each category and its projected-frame availability.
- **Approximate image count:** Approximately 2.5 million RGB-D views across
  more than 1,500 scans. These are temporally related scan frames, not
  independent still images.
- **Annotation format and quality:** 3D instance/semantic mesh annotations
  with 2D label and instance projections for frames. Converting visible
  projections to 2D boxes is possible but requires projection checks and
  filtering for small, truncated, or occluded instances. Keep all frames from
  each scan in one split.
- **License and commercial use:** The official repository requires a completed
  [ScanNet Terms of Use](http://kaldir.vc.in.tum.de/scannet/ScanNet_TOS.pdf)
  for access. It is not automatically commercially cleared; obtain approval
  and verify the agreement before using data in a commercial model or
  redistributing derived data.
- **YOLO fine-tuning:** **Conditionally suitable** as a supplemental source
  after agreement, conversion, and QA. It is less direct than Open Images or
  COCO for this 2D detection task and is not expected to fill cable/footwear
  gaps.

### 7. Objects365

- **Available classes:** 365 general object categories across roughly
  2 million images. It includes broad object-detection categories and is a
  possible source of furniture, household-object, and footwear examples; map
  its official class list to P6-1 before use. It is not indoor-focused, and
  per-class counts for this taxonomy should be checked rather than assumed.
- **Approximate image count:** About 2 million images and 30 million bounding
  boxes, according to the dataset overview.
- **Annotation format and quality:** Bounding-box annotations across 365
  categories. Convert boxes to YOLO and inspect category mapping, completeness,
  and indoor-scene relevance before use.
- **License and commercial use:** The official [download terms](https://www.objects365.org/download.html)
  state the dataset is available for academic purposes only. The consortium
  does not own image copyrights, places responsibility on users, and says
  images will not be distributed by users. **Not recommended for commercial
  fine-tuning without separate written permission.**
- **YOLO fine-tuning:** **Technically suitable after conversion**, but
  **not a recommended commercial source** under the published restriction.

## P6-1 class coverage and gaps

“Open Images” entries below refer to labels in its boxable taxonomy; synonymous
or broader labels require a documented mapping and annotation review.

| P6-1 class | Public-source coverage | Main limitation / recommended action |
|---|---|---|
| `person` | COCO; Open Images `Person` | Keep indoor examples only. The current app filter excludes person; dataset inclusion alone will not change runtime behavior. |
| `chair` | COCO; Open Images `Chair`; indoor datasets | Indoor, unobstructed views may be sparse in broad web datasets. |
| `couch` | COCO; Open Images `Couch`/`Loveseat`; indoor datasets | Normalize loveseat/sofa mapping to one approved class. |
| `bed` | COCO; Open Images `Bed`; indoor datasets | Include varied room layouts and partially occluded beds. |
| `table` | Open Images `Table`, `Coffee table`, and `Kitchen & dining room table`; COCO only has `dining table` | Merge only after manual mapping to the broader P6-1 definition; supplement with project captures. |
| `door` | Open Images `Door`; indoor scene datasets | Open/partially open doors and doorways need consistent P6-1 labels. |
| `stairs` | Open Images `Stairs`; indoor scene datasets may provide scene/segmentation labels | Include stair configurations and view angles; supplement with project captures. |
| `cabinet` | Open Images `Cabinetry`; indoor scene datasets | `Cabinetry` may represent cabinet banks rather than the P6-1 instance rule; review and normalize. |
| `refrigerator` | COCO; Open Images `Refrigerator`; indoor datasets | Good candidate for reusing boxes after indoor filtering. |
| `microwave` | COCO; Open Images `Microwave oven` | Normalize the synonymous Open Images label. |
| `sink` | COCO; Open Images `Sink`; indoor datasets | Review bathrooms and kitchens; avoid mapping tubs/showers as sinks. |
| `toilet` | COCO; Open Images `Toilet`; indoor datasets | Check full-fixture visibility and consistent tank/bowl boundaries. |
| `potted plant` | COCO; Open Images `Houseplant`/plant-related labels | Map only when the plant and pot match the approved definition. |
| `backpack` | COCO; Open Images `Backpack` | Include carried, stored, and floor examples; verify image rights. |
| `handbag` | COCO; Open Images `Handbag` | Distinguish from shopping bags and backpacks. |
| `suitcase` | COCO; Open Images `Suitcase`/`Luggage and bags` | Use only clearly identifiable suitcases for this class. |
| `bottle` | COCO; Open Images `Bottle` | Filter indoor scenes and preserve consistent bottle-versus-container boundaries. |
| `footwear` | Open Images `Footwear`; Objects365 may provide shoe categories | Public labels may split footwear into subtypes; merge only by an explicit mapping. |
| `box` | Open Images `Box`; Objects365 may provide box-like categories | Verify rigid storage/carton definition; exclude package depictions. |
| `cable` | No dedicated COCO or Open Images boxable class identified | **Largest coverage gap.** Collect and label project-owned examples across floor surfaces, lighting, distance, and cable visibility. |

### Practical gaps to address

- **Cable:** No direct boxable class was found in the reviewed COCO or Open Images
  taxonomies. Plan first-party collection and manual labels.
- **Doors and stairs:** Open Images has relevant boxable labels, but confirm
  indoor counts and adapt its boundaries to the P6-1 doorway/flight rules.
- **Footwear and boxes:** Open Images has `Footwear` and `Box`; Objects365 may
  offer shoe-related categories. These sources still need indoor-context,
  taxonomy, and license filtering.
- **Cabinets and tables:** Open Images has useful related labels, but `Cabinetry`
  and multiple table categories do not automatically match the project's
  instance definitions.
- **All classes:** A large source image count does not mean a large indoor,
  legally usable, exhaustively boxed count for each target class. Measure
  verified per-class counts before selecting source subsets.
- **Negative/background reliability:** Do not treat an image as a negative
  example for a target class unless that class was checked and exhaustively
  labeled in the image. Existing datasets annotate different label sets and
  may leave other P6-1 objects unlabeled.

## Recommended source priorities

1. **Open Images V7** for lawful, attribution-compliant candidate images and
   boxes after per-image license checks, indoor-scene filtering, and taxonomy
   normalization.
2. **COCO 2017** for COCO-backed categories, with source-image rights and
   attribution verified and `dining table` kept distinct from broader `table`
   labels until reviewed.
3. **Project-captured images** for all classes, with priority on cables, doors,
   stairs, footwear, and floor-level boxes. Obtain consent and maintain a
   rights manifest.
4. **ADE20K, SUN RGB-D, and ScanNet** only as supplemental sources after access
   and commercial-use terms are confirmed. Keep their source/room groups
   intact during splitting.
5. **Objects365** only for noncommercial academic experiments unless the
   dataset owner grants broader rights in writing.

For any accepted source, convert only reviewed annotations, remap them to the
fixed class IDs in P6-1, preserve source/license metadata, deduplicate images,
and assign room/session groups before applying the 70:20:10 split. Do not merge
images from existing evaluation sets into training unless their role is
explicitly changed and the held-out test remains independent.

## References

- [Approved P6-1 Indoor Dataset Specification](./INDOOR_DATASET_SPECIFICATION.md)
- [Open Images V7 overview](https://storage.googleapis.com/openimages/web/index.html)
- [Open Images V7 facts, figures, annotation quality, and license](https://storage.googleapis.com/openimages/web/factsfigures_v7.html)
- [Open Images V7 download and annotation formats](https://storage.googleapis.com/openimages/web/download_v7.html)
- [Open Images boxable class descriptions](https://storage.googleapis.com/openimages/v7/oidv7-class-descriptions-boxable.csv)
- [COCO dataset terms of use](https://cocodataset.org/#termsofuse)
- [Objects365 overview](https://www.objects365.org/overview.html) and [download terms](https://www.objects365.org/download.html)
- [ADE20K repository description](https://github.com/CSAILVision/ADE20K) and [terms of use](https://ade20k.csail.mit.edu/terms)
- [SUN RGB-D project page](https://rgbd.cs.princeton.edu/)
- [ScanNet repository](https://github.com/ScanNet/ScanNet) and [Terms of Use](http://kaldir.vc.in.tum.de/scannet/ScanNet_TOS.pdf)
