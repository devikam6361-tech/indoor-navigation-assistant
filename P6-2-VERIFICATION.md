---
phase: P6-2
verified: 2026-11-15
status: gaps_found
score: 6/8 top-level checks fully verified
is_re_verification: true
---

# P6-2 Final Verification Audit

**Scope:** Compare the approved P6-1 class specification with the P6-2 source
research report and verify its source, taxonomy, and licensing claims. This is
an audit only; no datasets were downloaded and no production files were changed.

## Final evidence checklist

| Check | Status | Evidence / finding |
|---|---|---|
| The source report uses the same 20 class names and IDs as P6-1 | **PASS** | The specification defines IDs 0–19; the report crosswalk lists all 20 in the same order. |
| Objects365 V2 Bottle mapping is complete | **PASS** | The source report now records Bottle in V1 and V2, based on the [V2 class tuple](https://github.com/open-mmlab/mmdetection/blob/cfd5d3a985b0249de009b67d04f37263e11cdf3d/mmdet/datasets/objects365.py). |
| V2 `Dinning Table` spelling is investigated without changing P6-1 | **PASS** | The [adapter](https://github.com/open-mmlab/mmdetection/blob/cfd5d3a985b0249de009b67d04f37263e11cdf3d/mmdet/datasets/objects365.py) spells the source label `Dinning Table`; V1 spells it `dining table`. The P6-1 class remains ID 4, `table`. Publisher intent behind the V2 spelling remains unverified. |
| Source-to-P6 boundaries for table, door, stairs, and cabinet are established | **UNVERIFIED** | The report preserves the P6-1 definitions and marks dataset mappings as candidates; source taxonomy labels do not establish matching box boundaries/grouping. |
| Licensing layers are documented separately and claims are supported or marked unknown | **PASS** | The source report now separates image, annotation/data, software, and commercial permissions. COCO, ADE20K, SUN RGB-D, and ScanNet data permissions remain explicitly unverified. |
| Cable gap is explicitly documented | **PASS** | No dedicated cable box label was found in the reviewed taxonomies; first-party collection remains the stated route. |
| Open Images is proven sufficient for the indoor collection targets | **UNVERIFIED** | Open Images supports candidate labels for 19 classes, but published totals do not establish indoor-scene or per-class counts. The report keeps this unverified. |
| Academic-only source is not recommended for commercial use | **PASS** | Objects365's official terms say academic purposes only; the report does not recommend it for commercial training. |

## Class-by-class cross-check

`PASS` here means a relevant category name is verified in at least one named
source, not that enough licensed indoor instances are available. `UNVERIFIED`
means the mapping is broader/narrower than the P6-1 definition or only
taxonomy-level evidence is available. `FAIL` means the current report's
crosswalk is incomplete or incorrect.

| ID | P6-1 class | Mapping evidence checked | Status |
|---:|---|---|---|
| 0 | `person` | COCO `person`; Open Images `Person`; Objects365 person; SUN RGB-D person | **PASS** |
| 1 | `chair` | COCO/Open Images/Objects365 `chair`; SUN RGB-D chair | **PASS** |
| 2 | `couch` | COCO/Open Images/Objects365 couch; SUN RGB-D `sofa` equivalent | **PASS** |
| 3 | `bed` | COCO/Open Images/Objects365 `bed`; SUN RGB-D bed | **PASS** |
| 4 | `table` | COCO `dining table`; Open Images Table/Coffee table/Kitchen & dining room table; Objects365 `dining table` (V1), `Dinning Table` (V2), Coffee Table, Side Table; SUN RGB-D table | **UNVERIFIED** — multiple labels do not automatically match the broader P6-1 table boundary. |
| 5 | `door` | Open Images Door; SUN RGB-D door; absent from COCO and reviewed Objects365 mapping | **UNVERIFIED** — P6-1 labels a doorway assembly, not necessarily the source's door box. |
| 6 | `stairs` | Open Images Stairs; no corresponding COCO, Objects365, or SUN RGB-D label found | **UNVERIFIED** — category exists, but indoor instance counts and P6-1 flight boundaries are unknown. |
| 7 | `cabinet` | Open Images Cabinetry; Objects365 Cabinet/shelf; SUN RGB-D cabinet | **UNVERIFIED** — cabinetry/shelf groupings may differ from the P6-1 cabinet-instance rule. |
| 8 | `refrigerator` | COCO/Open Images/Objects365 refrigerator; SUN RGB-D fridge | **PASS** |
| 9 | `microwave` | COCO microwave; Open Images Microwave oven; Objects365 microwave | **PASS** |
| 10 | `sink` | COCO/Open Images/Objects365 sink; SUN RGB-D sink | **PASS** |
| 11 | `toilet` | COCO/Open Images/Objects365 toilet; SUN RGB-D toilet | **PASS** |
| 12 | `potted plant` | COCO and Objects365 Potted Plant; Open Images Houseplant | **PASS** — Open Images `Houseplant` remains a candidate mapping because P6-1 requires the plant together with its pot. |
| 13 | `backpack` | COCO/Open Images/Objects365 backpack; SUN RGB-D `bag` is broader | **PASS** |
| 14 | `handbag` | COCO/Open Images/Objects365 handbag/satchel; SUN RGB-D `bag` is broader | **PASS** |
| 15 | `suitcase` | COCO/Open Images/Objects365 V1 suitcase; Objects365 V2 Luggage | **PASS** — V2 `Luggage` is broader and should not be treated as exact without review. |
| 16 | `bottle` | COCO/Open Images bottle; Objects365 V1 and V2 Bottle | **PASS** |
| 17 | `footwear` | Open Images Footwear; Objects365 shoe/boot/slipper/sandal subcategories | **PASS** — Objects365 subcategories require an explicit merge policy. |
| 18 | `box` | Open Images Box; Objects365 Storage box; SUN RGB-D box | **PASS** — apply the P6-1 rigid-box definition; generic boxes may need filtering. |
| 19 | `cable` | No dedicated boxable label in reviewed COCO, Open Images, Objects365, or SUN RGB-D taxonomies | **PASS** — correctly documented as a data-collection gap. |

ADE20K and ScanNet are correctly excluded from the per-class table as
**unverified**: the accessible evidence does not establish image-level P6-1
class coverage or per-class counts.

## Licensing audit

| Source | Image rights | Annotation/data rights | Software license | Commercial-use status |
|---|---|---|---|---|
| Open Images V7 | Official facts page lists images as CC BY 2.0 but disclaims image-level warranties; verify each image. | Official facts page: annotations CC BY 4.0. | The separate [dataset repository](https://github.com/openimages/dataset/blob/master/LICENSE) is Apache 2.0 for repository software only. | Conditional on verifying the image's actual license/attribution; no blanket clearance. |
| COCO 2017 | **UNVERIFIED**; official terms endpoint was inaccessible. | **UNVERIFIED**; no annotation-data grant confirmed in this review. | [COCO API](https://github.com/cocodataset/cocoapi/blob/master/license.txt) has BSD-style software terms only. | **UNVERIFIED**; no commercial data clearance claimed. |
| Objects365 | Consortium says it does not own image copyrights, references source-image terms, places responsibility on users, and prohibits image redistribution. | Official terms: website and annotations CC BY 4.0. | Official terms: provided software MIT. | Academic purposes only; not recommended for commercial training. Terms show no waiver process. |
| ADE20K | Governed by official terms; exact image rights not verified. | Governed by official terms; exact annotation rights not verified. | No repository-root software license identified in the reviewed listing. | **UNVERIFIED**; no commercial permission claimed. |
| SUN RGB-D | **UNVERIFIED**; no blanket/image-level rights established. | **UNVERIFIED**; metadata reference is not a license grant. | No license file identified at metadata repository root; this does not establish a license status. | **UNVERIFIED**. |
| ScanNet | Dataset governed by Terms of Use; terms content inaccessible. | Dataset labels/projections governed by the data terms; exact scope unverified. | Repository code MIT, separate from data terms. | **UNVERIFIED**; no commercial permission claimed. |

**Commercial recommendation check:** Objects365 is explicitly academic-purpose
only in its official terms and is not recommended for commercial training in
the research report. The report avoids commercial clearance claims for the
other rights-unverified sources. Do not interpret this audit as legal clearance
for any source.

## Open Images feasibility

- **Taxonomy coverage — PASS:** the official
  [V7 boxable-class list](https://storage.googleapis.com/openimages/v7/oidv7-class-descriptions-boxable.csv)
  contains direct or close labels for 19 P6-1 classes; no dedicated cable
  label was found.
- **Scale — PASS as a candidate source:** official V7 facts report boxes on
  1,743,042 training images, 41,620 validation images, and 125,436 test images,
  across 600 boxable categories. The annotations include visibility and
  grouping flags useful for filtering.
- **Indoor sufficiency — UNVERIFIED:** these are broad web images, not an
  indoor-only source. The cited overall counts do not give verified indoor
  counts for each target category. The report's recommendation is reasonable
  only as a candidate source, not a guarantee of meeting P6-1 targets.
- **Annotation caveat — PASS:** the official facts page describes exhaustive
  boxes for positive boxed labels except group cases. The report now requires
  per-class review of `IsDepiction`, `IsGroupOf`, truncation, and occlusion
  flags against the P6-1 rules before converting boxes.

## Unsupported, ambiguous, or incomplete findings

1. **Objects365 V2 bottle omission — CORRECTED:** the report now records
   `Bottle` in both V1 and V2, as shown in the adapter's class tuples.
2. **Objects365 table spelling — INVESTIGATED; intent UNVERIFIED:** the
   [adapter](https://github.com/open-mmlab/mmdetection/blob/cfd5d3a985b0249de009b67d04f37263e11cdf3d/mmdet/datasets/objects365.py)'s
   V2 class string is `Dinning Table`; V1 is `dining table`. The
   report preserves both source spellings and does not change P6-1 ID 4 or its
   class name `table`. Only the adapter spelling—not the dataset publisher's
   intended taxonomy—was verified.
3. **Table, door, stairs, cabinet boundaries — UNVERIFIED:** the report now
   compares the P6-1 rules with source labels and explicitly avoids claiming
   source box-boundary equivalence.
4. **Objects365 footwear, luggage, and storage-box mappings — AMBIGUOUS, now
   qualified:** multiple footwear subtypes and `Storage box` need a merge/filter
   policy; V2 `Luggage` is explicitly marked as broader than P6-1 `suitcase`.
5. **Open Images realism — UNVERIFIED:** label existence does not prove
   enough indoor examples. Counts by target class after indoor and rights
   filtering remain unmeasured.
6. **Objects365 licensing detail — CORRECTED:** the report now records CC BY
   4.0 for annotations/website and MIT for software, distinct from image rights
   and academic-only use.
7. **COCO/ADE20K/SUN RGB-D/ScanNet terms — UNVERIFIED:** the report properly
   avoids claiming commercial clearance, but final source approval remains
   blocked on reviewing their applicable image/data terms.

## Remaining UNVERIFIED items

- Whether the Objects365 publisher intended V2 `Dinning Table` to mean
  `Dining Table`; only the adapter spelling and V1 spelling were verified.
- Whether any source's table, door, stairs, or cabinet boxes follow the exact
  P6-1 boundaries and instance-grouping rules.
- Whether Open Images provides enough indoor, rights-cleared examples for the
  required counts in any target class; image-level/per-class filtering evidence
  has not been gathered.
- COCO image and annotation permissions; the official terms page was
  inaccessible during this audit.
- ADE20K image/annotation permissions and its software license; the terms page
  was inaccessible and no repository-root software license was identified.
- SUN RGB-D image/annotation permissions and helper-software license; no
  license grant was identified in the reviewed metadata reference.
- ScanNet image/annotation commercial scope; its Terms of Use was not
  inspectable during this audit, although the official README confirms the
  agreement is required.
- Any case-specific image rights/attribution for Open Images or source-image
  rights for Objects365.

## Verdict

**Status: GAPS FOUND.** The 20-class order matches the approved specification;
the Objects365 V2 Bottle discrepancy is corrected; `Dinning Table` is
documented without changing P6-1 ID 4/name; the cable gap is explicit; and
Objects365's academic-only restriction is handled conservatively. Source
box-boundary equivalence for table, door, stairs, and cabinet remains
unverified. COCO, ADE20K, SUN RGB-D, and ScanNet data rights and Open Images'
ability to meet indoor per-class counts also remain unverified.

No P6-3 work is authorized or started by this audit.
