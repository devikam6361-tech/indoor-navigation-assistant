# Indoor Dataset Source Research

**Phase:** P6-2 — Indoor Dataset Source Research
**Basis:** Approved [P6-1 dataset specification](./INDOOR_DATASET_SPECIFICATION.md)
**Scope:** Source verification only. No images or datasets were downloaded.

## Executive summary

No reviewed source is both a license-cleared, indoor-only, ready-to-use YOLO
dataset for all 20 P6-1 classes.

- **Open Images V7** is the broadest candidate for existing 2D boxes: its
  boxable taxonomy has direct or close labels for 19 of the 20 target classes.
  It does not have a dedicated cable label. Indoor relevance, per-class counts,
  and rights must still be checked image by image.
- **COCO 2017** provides native boxes for the 13 COCO-backed classes. Its
  `dining table` category is narrower than P6-1 `table`. COCO's image-use terms
  were not independently verified in this review; the COCO API code license is
  not a license for the dataset images.
- **Objects365** has native box annotations and many relevant categories, but
  its published terms restrict use to academic purposes. Do not use it for
  commercial training without separate written permission.
- **SUN RGB-D** has relevant indoor categories, but the reviewed 37-class
  annotation source provides semantic segmentation labels, not ready-made
  2D YOLO boxes. Its image-use rights remain unverified.
- **ADE20K** and **ScanNet** offer useful indoor segmentation/context data, but
  exact P6-1 class coverage, box-conversion effort, and commercial permissions
  are not fully verified from accessible source material.
- **Project-captured, consented images** are the most controllable source for
  all 20 definitions and are necessary to cover cables reliably.

### Evidence labels used below

- **Verified:** stated in an official dataset source, or in a named public
  taxonomy/annotation reference where identified.
- **Approximate:** dataset-wide published count, rounded for planning. It is
  not a count of indoor images or any individual target class.
- **Unverified:** not established by the accessible evidence in this review.
  Do not treat it as permission or confirmed class coverage.

“Suitable for YOLO fine-tuning” describes technical annotation suitability,
not permission to use the data. Free access does not imply commercial rights,
redistribution permission, or permission to publish derived datasets. This
research is not legal advice.

## Source-by-source assessment

### 1. Open Images V7

- **Classes:** The official boxable taxonomy includes direct or close labels
  for `Person`, `Chair`, `Couch`, `Bed`, `Table`, `Coffee table`,
  `Kitchen & dining room table`, `Door`, `Stairs`, `Cabinetry`,
  `Refrigerator`, `Microwave oven`, `Sink`, `Toilet`, `Houseplant`,
  `Backpack`, `Handbag`, `Suitcase`, `Bottle`, `Footwear`, and `Box`.
  This supports candidate mappings for 19 P6-1 classes. `Houseplant`,
  `Cabinetry`, and the multiple table labels require review against the P6-1
  instance definitions. No dedicated boxable `cable` class was found.
- **Image count:** **Approximate, verified at dataset level:** about 9.18M
  images overall. Official V7 figures report boxes on 1,743,042 train,
  41,620 validation, and 125,436 test images. Those figures do not establish
  how many images contain indoor scenes or any particular target class.
- **Annotation format/quality:** **Verified:** box annotations are CSV records
  with normalized coordinates and flags including occlusion, truncation,
  group-of, depiction, and inside. The official facts page reports 14.6M
  training boxes across 600 boxable classes; most were manually drawn, and the
  semi-automated portion was human-verified. Validation/test boxes were
  manually drawn. Convert XYXY boxes to YOLO center/width/height and manually
  audit taxonomy mappings and completeness.
- **License/commercial use:** **Verified with a per-image caveat:** the official
  documentation describes images as CC BY 2.0 and annotations as CC BY 4.0,
  but disclaims warranties about image licenses and directs users to verify
  each image's rights. Commercial use is conditional on the actual image
  license, attribution, and other rights; the collection is not blanket
  clearance.
- **YOLO suitability:** **Technically suitable after filtering and conversion.**
  Strongest public candidate for door, stairs, footwear, and box annotations.
  Filter for actual indoor scenes, retain attribution/license records, and add
  cable examples from a separately cleared source. The official box CSV exposes
  `IsDepiction` and `IsGroupOf` flags; review them per class against the P6-1
  annotation rules, and exclude or re-annotate cases that conflict with those
  rules. Review truncation and occlusion flags against the P6-1 visibility
  threshold.

### 2. COCO 2017

- **Classes:** **Verified:** exact P6-1 COCO-backed categories are `person`,
  `chair`, `couch`, `bed`, `refrigerator`, `microwave`, `sink`, `toilet`,
  `potted plant`, `backpack`, `handbag`, `suitcase`, and `bottle`.
  COCO `dining table` is a related but narrower label for P6-1 `table`.
  It does not supply the other six custom classes.
- **Image count:** **Approximate:** about 118K train, 5K validation, and 41K
  test images. Train/validation annotations are available for supervised use;
  test annotations are not generally available for local training.
- **Annotation format/quality:** **Verified:** instance annotations in JSON
  include bounding boxes and segmentation annotations for 80 categories.
  Boxes can be remapped to the stable P6-1 IDs. The images are general-purpose
  web photos, not an indoor-only set; the number of usable indoor examples per
  class is unverified.
- **License/commercial use:** **Unverified in this review:** the official
  [COCO terms page](https://cocodataset.org/#termsofuse) is the relevant source,
  but its current image-use terms could not be independently confirmed here.
  The BSD license in the [COCO API repository](https://github.com/cocodataset/cocoapi/blob/master/license.txt)
  applies to API code, not to the Flickr images. Do not infer image rights from
  the API license or assume blanket commercial clearance; review the current
  terms and source-image rights before use.
- **YOLO suitability:** **Technically suitable for the 13 COCO-backed classes**
  after JSON conversion and remapping. Keep `dining table` distinct from the
  broader P6-1 `table` unless a reviewed mapping is applied.

### 3. Objects365

- **Classes:** **Class names verified against the V1/V2 class tuples in the
  third-party [MMDetection Objects365 adapter](https://github.com/open-mmlab/mmdetection/blob/cfd5d3a985b0249de009b67d04f37263e11cdf3d/mmdet/datasets/objects365.py);
  this is a technical cross-reference, not an official publisher taxonomy or
  the dataset's license.**
  It includes labels/equivalents such as person, chair, couch, bed,
  cabinet/shelf, refrigerator, microwave, sink, toilet, potted plant,
  backpack, handbag/satchel, suitcase (V1)/luggage (V2, broader candidate),
  bottle (V1 and V2),
  dining/coffee/side table, storage box, and multiple shoe types. The reviewed
  taxonomy does not contain dedicated door or stairs categories. The V2
  adapter's literal category string is `Dinning Table` (sic); V1 has
  `dining table`. The spelling in the V2 adapter appears to be a typo, but the
  publisher's intended spelling was not independently confirmed. This is only
  a source-label note; the P6-1 class remains ID 4, `table`. `Extension cord`
  is not equivalent to P6-1's general loose `cable` class. Per-class image
  counts and indoor subset counts are unverified.
- **Image count:** **Approximate, official overview:** about 2M images and
  30M bounding boxes across 365 categories.
- **Annotation format/quality:** **Verified:** object detection boxes with
  COCO-style annotations; the adapter parses per-image annotation records.
  Indoor relevance, class-specific completeness, and label consistency against
  P6-1 need manual checks.
- **License/commercial use:** **Verified restriction:** the official
  [download terms](https://www.objects365.org/download.html) state academic
  purposes only. The same page says the consortium does not own image
  copyrights, places responsibility on users, and prohibits redistribution of
  images. It separately licenses the annotations and website under CC BY 4.0
  and the provided software under MIT; neither license grants rights to the
  images. **Do not use for commercial training under the published
  academic-only terms.** The terms page does not document a waiver process;
  any separate authorization would have to be obtained from the relevant
  rights holder and verified independently.
- **YOLO suitability:** **Technically suitable for noncommercial research**
  after conversion and audit. Not recommended for commercial fine-tuning under
  the published terms.

### 4. ADE20K

- **Classes:** **Unverified for the P6-1 crosswalk:** the official project
  describes broad scene, object, and object-part segmentation across 3,688
  categories. Accessible material did not establish exact image-level coverage
  for each of the 20 P6-1 classes. Do not count possible labels such as door,
  stairs, or cabinet as confirmed examples without checking the released
  category index and annotations.
- **Image count:** **Verified in the official repository description:**
  27,574 images (25,574 training and 2,000 test) across 365 scene types.
- **Annotation format/quality:** **Verified at dataset level:** segmentation
  masks/polygons and per-image metadata include object/part information.
  These are not ready-made P6-1 YOLO boxes. Box derivation requires category
  mapping, instance-boundary review, and manual QA.
- **License/commercial use:** The official [terms page](https://ade20k.csail.mit.edu/terms)
  is linked by the project. **Specific commercial permissions were not verified
  in this review**; treat use as restricted until the applicable terms and
  access conditions are reviewed.
- **YOLO suitability:** **Conditional supplement only** after confirming exact
  class presence, annotation instance semantics, conversion feasibility, and
  rights.

### 5. SUN RGB-D

- **Classes:** The [SUN RGB-D project](https://rgbd.cs.princeton.edu/) is an
  indoor RGB-D dataset. A public
  [annotation-metadata repository](https://github.com/ankurhanda/sunrgbd-meta-data)
  documents 37 semantic labels, including `person`, `chair`, `sofa`, `bed`,
  `table`, `door`, `cabinet`, `fridge`, `box`, `toilet`, and `sink`.
  `bag` is broader than P6-1 `backpack`, `handbag`, or `suitcase`; it is not an
  exact match. The documented 37-class list does not include stairs, microwave,
  potted plant, footwear, bottle, or cable. This class list is from the
  metadata repository, not a verified per-class image count.
- **Image count:** **Verified by the project/metadata descriptions:**
  10,335 images total; the metadata README describes 5,285 training and 5,050
  test images.
- **Annotation format/quality:** The reviewed metadata repository provides
  per-image semantic segmentation label maps for 37 classes. It does **not**
  establish ready-made 2D object boxes for those labels. Semantic masks may
  merge adjacent same-class objects, so bounding boxes cannot always be
  generated as reliable per-instance labels. Do not describe this source as
  plug-and-play YOLO box data.
- **License/commercial use:** **Unverified:** the official project page and
  reviewed metadata repository did not establish a blanket commercial license
  or image-level rights. The metadata repository is not proof of image
  permission. Do not use until the dataset terms and rights are confirmed.
- **YOLO suitability:** **Limited/conditional.** Indoor scenes are relevant,
  but the reviewed labels are semantic masks rather than ready-made 2D boxes.
  Use only if an instance-safe conversion or independent re-annotation is
  feasible and rights are cleared.

### 6. ScanNet

- **Classes:** **Exact P6-1 instance coverage unverified:** the
  [official repository](https://github.com/ScanNet/ScanNet) describes a label
  mapping from ScanNet labels to NYUv2, ModelNet, ShapeNet, and WordNet
  categories. The task label map is distributed with task data, not listed in
  the repository itself. Candidate taxonomy overlap is not proof that each
  target category has labeled instances in the released RGB views. Verify
  actual label IDs and per-class image counts before mapping.
- **Image count:** **Approximate, official repository:** about 2.5M RGB-D views
  across more than 1,500 scans. Views from the same scan are related frames,
  not independent images.
- **Annotation format/quality:** **Verified:** 3D reconstructions and
  instance-level semantic labels are available, with 2D label/instance
  projections and helper scripts. No ready-made P6-1 YOLO box set was verified.
  Deriving 2D boxes from projections requires visibility, truncation, and
  instance-boundary QA. Keep all frames from a scan in one split.
- **License/commercial use:** **Verified access requirement; commercial scope
  unverified:** the official repository requires a completed
  [ScanNet Terms of Use](http://kaldir.vc.in.tum.de/scannet/ScanNet_TOS.pdf).
  The repository's MIT code license does not license dataset images. Review the
  signed data terms before any use or redistribution; commercial permission
  was not established here.
- **YOLO suitability:** **Conditional, high conversion effort.** Potentially
  useful for indoor context and selected classes after label-map verification,
  projection, QA, and agreement review.

### 7. Project-captured indoor images

- **Classes:** All 20 P6-1 classes can be deliberately captured and annotated;
  prioritize cable and ensure doors, stairs, footwear, and floor-level boxes
  are represented.
- **Image count:** No capture count is established. The P6-1 per-class targets
  are object-instance targets, not image counts.
- **Annotation format/quality:** Capture photos or carefully selected video
  frames and annotate directly to the P6-1 YOLO format. Apply one annotation
  guide and review protocol across all classes.
- **License/commercial use:** Rights can be controlled only if the project
  obtains documented image, property, and participant permissions as
  applicable. Record consent, restrictions, and any privacy processing in the
  capture manifest.
- **YOLO suitability:** **Strongly suitable** for indoor-specific examples
  and taxonomy gaps, provided capture rights and annotations are managed.

## P6-1 class coverage crosswalk

`—` means no corresponding category was found in the reviewed taxonomy; it
does not prove that no such object appears in a source image. `Candidate` means
the name is broader, narrower, or semantically close and must not be merged
without review. ADE20K and ScanNet are omitted from this class-level table
because exact P6-1 image-level coverage was not verified.

| P6-1 class | COCO | Open Images boxable label | Objects365 V1/V2 label | SUN RGB-D documented label |
|---|---|---|---|---|
| `person` | `person` | `Person` | `person` | `person` |
| `chair` | `chair` | `Chair` | `Chair` | `chair` |
| `couch` | `couch` | `Couch` | `couch` | `sofa` |
| `bed` | `bed` | `Bed` | `Bed` | `bed` |
| `table` | Candidate: `dining table` | `Table`, `Coffee table`, `Kitchen & dining room table` | `dining table` (V1), `Dinning Table` (V2, sic), `Coffee Table`, `Side Table` | `table` |
| `door` | — | `Door` | — | `door` |
| `stairs` | — | `Stairs` | — | — |
| `cabinet` | — | Candidate: `Cabinetry` | Candidate: `Cabinet/shelf` | `cabinet` |
| `refrigerator` | `refrigerator` | `Refrigerator` | `Refrigerator` | `fridge` |
| `microwave` | `microwave` | `Microwave oven` | `Microwave` | — |
| `sink` | `sink` | `Sink` | `Sink` | `sink` |
| `toilet` | `toilet` | `Toilet` | `Toilet` | `toilet` |
| `potted plant` | `potted plant` | Candidate: `Houseplant` | `Potted Plant` | — |
| `backpack` | `backpack` | `Backpack` | `Backpack` | Candidate: `bag` |
| `handbag` | `handbag` | `Handbag` | `Handbag/Satchel` | Candidate: `bag` |
| `suitcase` | `suitcase` | `Suitcase` | `Suitcase` (V1), candidate: broader `Luggage` (V2) | Candidate: `bag` |
| `bottle` | `bottle` | `Bottle` | `Bottle` (V1 and V2) | — |
| `footwear` | — | `Footwear` | Candidate: multiple shoe/boot/slipper/sandal classes | — |
| `box` | — | `Box` | Candidate: `Storage box` | `box` |
| `cable` | — | — | —; `Extension cord` is not equivalent to every loose cable | — |

This crosswalk proves category-name availability, not image-level instance
counts, indoor-scene prevalence, label completeness, or licensing.

### P6-1 boundary compatibility

The P6-1 definitions are the labeling contract. Dataset category names are
evidence of taxonomy coverage, not proof that the source annotators used the
same box boundaries or instance grouping. The reviewed official taxonomy and
annotation summaries do not provide enough per-class instructions to confirm
these four mappings:

| P6-1 class | P6-1 boundary | Source label(s) | Boundary status |
|---|---|---|---|
| `table` (ID 4) | Dining, coffee, side, or end table; exclude counters, desks, shelves, and cabinets. | COCO `dining table`; Open Images `Table`, `Coffee table`, `Kitchen & dining room table`; Objects365 dining/coffee/side table labels; SUN RGB-D `table`. | **UNVERIFIED** — source label coverage is promising, but the combined labels do not establish inclusion/exclusion or per-instance consistency for the P6-1 definition. |
| `door` (ID 5) | Doorway assembly including visible frame and door leaf/leaves; include open doors; exclude bare openings without an identifiable frame or door. | Open Images `Door`; SUN RGB-D `door`. | **UNVERIFIED** — the source taxonomy does not specify whether a box covers the door leaf, frame, or assembly. |
| `stairs` (ID 6) | One continuous flight with visible treads/risers and attached handrails; landing-separated flights are distinct. | Open Images `Stairs`. | **UNVERIFIED** — the category name does not establish whether source boxes group flights, landings, and handrails as P6-1 requires. |
| `cabinet` (ID 7) | One distinct cabinet or continuous built-in cabinet bank; do not split doors, drawers, or handles. | Open Images `Cabinetry`; Objects365 `Cabinet/shelf`; SUN RGB-D `cabinet`. | **UNVERIFIED** — these source labels can represent different aggregation levels; exact instance boundaries are not established. |

Until reviewed sample annotations or class-specific instructions establish
equivalence, these labels must remain candidate inputs for manual remapping or
re-annotation, not automatic P6-1 labels.

## Licensing layers and commercial-use status

Image rights, annotation rights, and software licenses are separate. A license
for an API, downloader, or annotation file does not grant rights to the
underlying images. “Unverified” means no permission should be inferred.

| Source | Image rights | Annotation/data rights | Software license | Commercial-use status |
|---|---|---|---|---|
| Open Images V7 | Official facts page lists images as CC BY 2.0, but disclaims image-level warranties; verify each image and attribution. | Official facts page: annotations CC BY 4.0. | The separate [Open Images dataset repository license](https://github.com/openimages/dataset/blob/master/LICENSE) is Apache 2.0 for repository software; it does not replace dataset/image terms. | **Conditional, not blanket-cleared:** only use images whose actual license and attribution requirements are verified. |
| COCO 2017 | **Unverified:** image-source and current dataset terms were not confirmed in this review. | **Unverified:** no separate annotation-data grant was confirmed; the official terms endpoint was inaccessible. | [COCO API code](https://github.com/cocodataset/cocoapi/blob/master/license.txt) is under BSD-style terms; that is a software license only. | **Unverified:** do not claim commercial image or annotation clearance until official terms and source-image rights are checked. |
| Objects365 | Official terms say the consortium does not own image copyright, images are subject to source terms, users bear responsibility, and image redistribution is prohibited. | Official terms license annotations and website under CC BY 4.0. | Official terms provide the software under MIT; this does not license images. | **Academic purposes only** under the published terms; not recommended for commercial training. No waiver path is stated. |
| ADE20K | Official README says data access/use is governed by the linked Terms of Use; exact image rights were not verified here. | Governed by the same data terms; exact annotation rights were not verified here. | No repository-root software license was identified in the reviewed repository listing; do not infer a code license. | **Unverified:** no commercial permission asserted. |
| SUN RGB-D | **Unverified:** no blanket image license or image-level permissions were established. | **Unverified:** the reviewed 37-class metadata reference does not state a data/annotation license. | No separate license file was identified at the reviewed metadata repository root; this is not proof of permission or of no other terms. | **Unverified:** do not use commercially until applicable source and dataset rights are established. |
| ScanNet | Dataset governed by the ScanNet Terms of Use; the signed terms were not accessible for review. | Dataset annotations/projections are part of the governed data; exact rights and restrictions remain unverified. | The separate [ScanNet repository code license](https://github.com/ScanNet/ScanNet/blob/master/LICENSE) is MIT. | **Unverified:** the data agreement is required; no commercial permission is claimed. |
| Project-captured images | Must be covered by applicable photographer, property, and participant permissions. | Project annotation rights depend on the capture/annotation agreements. | No dataset software license is involved unless separate tooling is used. | **Conditional on documented rights and consent; no automatic clearance.** |

Official evidence: [Open Images facts and license](https://storage.googleapis.com/openimages/web/factsfigures_v7.html);
[COCO terms](https://cocodataset.org/#termsofuse) and [API license](https://github.com/cocodataset/cocoapi/blob/master/license.txt);
[Objects365 terms](https://www.objects365.org/download.html);
[ADE20K README](https://github.com/CSAILVision/ADE20K/blob/main/README.md) and [terms](https://ade20k.csail.mit.edu/terms);
[SUN RGB-D metadata reference](https://github.com/ankurhanda/sunrgbd-meta-data);
and [ScanNet README/terms notice](https://github.com/ScanNet/ScanNet/blob/master/README.md).
Links to inaccessible terms pages are retained as authoritative review targets,
not as evidence of permission.

## Recommendations and unresolved gaps

1. **First choice for existing boxes: Open Images V7.** It has the broadest
   reviewed label coverage, but actual indoor counts and commercial rights must
   be checked per image. Keep the original label and license metadata.
2. **Capture project images for coverage control.** Use them for all classes,
   with highest priority on `cable`, and to correct weak indoor representation
   or category mismatch in public sources.
3. **Use COCO only after image-rights review.** It has native boxes for the
   13 COCO-backed categories; the COCO API software license does not establish
   dataset-image rights. Treat P6-1 `table` as broader than COCO `dining table`.
4. **Objects365 is for academic-only consideration.** It has relevant boxes
   and shoe/storage-box categories, but its terms prohibit assuming commercial
   use. `door`, `stairs`, and generic `cable` remain gaps.
5. **Treat ADE20K, SUN RGB-D, and ScanNet as conditional supplements.** Verify
   class instances, annotation-to-box feasibility, and applicable terms before
   selection. SUN RGB-D's reviewed labels are semantic segmentation masks;
   ScanNet requires task-label mapping and projection review.

### Outstanding verification

- **Per-class counts:** None of the reviewed sources provided verified counts
  of legally usable indoor images or instances for every P6-1 class. Obtain
  these only after filtering the actual annotations and rights records.
- **Cable:** No dedicated boxable cable category was found in COCO or Open
  Images. Objects365 `Extension cord` is not a substitute for the P6-1 class.
  Plan direct collection and labeling.
- **Door/stairs/footwear/box:** Open Images supplies candidate box labels for
  all four. Objects365 supplies multiple shoe labels and storage boxes but no
  dedicated door/stairs categories in the reviewed taxonomy. Indoor counts and
  instance-rule compatibility remain unverified.
- **Image rights:** COCO, SUN RGB-D, ADE20K, and ScanNet commercial permissions
  were not established in this review. Do not treat access, code licenses, or
  annotations as image-use permission.
- **Incomplete labels:** Do not use images as negative examples for a target
  class unless that class has been checked and exhaustively labeled; otherwise
  unlabeled objects can become false background.
- **Split integrity:** Keep the P6-1 70:20:10 split grouped by physical room,
  capture session, and source scan. Deduplicate images and near-identical
  frames before splitting.

## Official and supporting references

- [P6-1 Indoor Dataset Specification](./INDOOR_DATASET_SPECIFICATION.md)
- Open Images V7: [overview](https://storage.googleapis.com/openimages/web/index.html),
  [facts, figures, annotation quality and license](https://storage.googleapis.com/openimages/web/factsfigures_v7.html),
  [download/annotation format](https://storage.googleapis.com/openimages/web/download_v7.html),
  and [boxable class descriptions](https://storage.googleapis.com/openimages/v7/oidv7-class-descriptions-boxable.csv)
- COCO: [official dataset site](https://cocodataset.org/),
  [terms of use](https://cocodataset.org/#termsofuse), and
  [COCO API code license](https://github.com/cocodataset/cocoapi/blob/master/license.txt)
- Objects365: [official overview](https://www.objects365.org/overview.html),
  [official download terms](https://www.objects365.org/download.html), and
  [published V1/V2 class mapping in MMDetection](https://github.com/open-mmlab/mmdetection/blob/cfd5d3a985b0249de009b67d04f37263e11cdf3d/mmdet/datasets/objects365.py)
- ADE20K: [official repository and dataset description](https://github.com/CSAILVision/ADE20K)
  and [terms of use](https://ade20k.csail.mit.edu/terms)
- SUN RGB-D: [official project page](https://rgbd.cs.princeton.edu/) and
  [public 37-class segmentation metadata reference](https://github.com/ankurhanda/sunrgbd-meta-data)
- ScanNet: [official repository and dataset description](https://github.com/ScanNet/ScanNet)
  and [Terms of Use](http://kaldir.vc.in.tum.de/scannet/ScanNet_TOS.pdf)

No source is approved here for collection, download, training, or P6-3. This
report finalizes research findings and should be reviewed before any data
acquisition.
