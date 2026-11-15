---
phase: P6-2
verified: 2026-11-15
status: gaps_found
score: 3/6 top-level checks fully verified
is_re_verification: false
---

# P6-2 Final Verification Audit

**Scope:** Compare the approved P6-1 class specification with the P6-2 source
research report and verify its source, taxonomy, and licensing claims. This is
an audit only; no datasets were downloaded and no production files were changed.

## Final evidence checklist

| Check | Status | Evidence / finding |
|---|---|---|
| The source report uses the same 20 class names and IDs as P6-1 | **PASS** | The specification defines IDs 0–19; the report crosswalk lists all 20 in the same order. |
| Every source mapping is complete and unambiguous | **FAIL** | The Objects365 V2 `Bottle` label is omitted from the report's V1/V2 crosswalk. Several mappings also need to remain explicitly qualified as candidates. |
| Affirmative licensing claims have official support, and unknown rights are marked unknown | **UNVERIFIED** | Open Images and Objects365 claims are supported by official pages. COCO, ADE20K, SUN RGB-D, and ScanNet commercial rights remain unverified. Objects365's annotation/website CC BY 4.0 license is omitted from the report. |
| Cable gap is explicitly documented | **PASS** | The report says no dedicated cable box label was found and recommends first-party collection. The Objects365 extension-cord label is correctly not treated as equivalent to loose cable. |
| Open Images is proven sufficient for the indoor collection targets | **UNVERIFIED** | The boxable taxonomy supports candidates for 19 classes, but published totals do not establish indoor-scene or per-class counts. |
| Academic-only source is not recommended for commercial use | **PASS** | Objects365's official download terms say academic purpose only; the report does not recommend it for commercial training. |

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
| 4 | `table` | COCO `dining table`; Open Images Table/Coffee table/Kitchen & dining room table; Objects365 dining/coffee/side table; SUN RGB-D table | **UNVERIFIED** — multiple labels do not automatically match the broader P6-1 table boundary. |
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
| 16 | `bottle` | COCO/Open Images bottle; Objects365 V1 **and V2** Bottle | **FAIL** — the report lists Objects365 Bottle as V1 only, omitting V2. |
| 17 | `footwear` | Open Images Footwear; Objects365 shoe/boot/slipper/sandal subcategories | **PASS** — Objects365 subcategories require an explicit merge policy. |
| 18 | `box` | Open Images Box; Objects365 Storage box; SUN RGB-D box | **PASS** — apply the P6-1 rigid-box definition; generic boxes may need filtering. |
| 19 | `cable` | No dedicated boxable label in reviewed COCO, Open Images, Objects365, or SUN RGB-D taxonomies | **PASS** — correctly documented as a data-collection gap. |

ADE20K and ScanNet are correctly excluded from the per-class table as
**unverified**: the accessible evidence does not establish image-level P6-1
class coverage or per-class counts.

## Licensing audit

| Source | Status | Official evidence and limits |
|---|---|---|
| Open Images V7 | **PASS, with per-image verification required** | The official [facts and figures](https://storage.googleapis.com/openimages/web/factsfigures_v7.html) say annotations are CC BY 4.0 and images are listed as CC BY 2.0, while expressly disclaiming license warranties and requiring users to verify each image. |
| COCO | **UNVERIFIED** | The report correctly marks current image-use terms unverified and links the [official COCO terms page](https://cocodataset.org/#termsofuse). That endpoint was inaccessible during this audit. The [COCO API license file](https://github.com/cocodataset/cocoapi/blob/master/license.txt) licenses the API code, not the dataset images. |
| Objects365 | **PASS for academic-only restriction; incomplete license summary** | The [official download terms](https://www.objects365.org/download.html) state academic purpose only, license annotations and the website under CC BY 4.0, say the consortium does not own image copyrights, put responsibility on users, and prohibit redistribution of the images. The research report omits the annotation/website CC BY 4.0 detail. Its “unless separate written permission” wording is prudent caveat language, not a documented exception process in the cited terms. |
| ADE20K | **UNVERIFIED** | The [official repository README](https://github.com/CSAILVision/ADE20K/blob/main/README.md) directs users to the [Terms of Use](https://ade20k.csail.mit.edu/terms). The terms page was inaccessible during this audit; no commercial permission is asserted in the report. |
| SUN RGB-D | **UNVERIFIED** | The report makes no affirmative commercial-use claim. The public [37-class metadata reference](https://github.com/ankurhanda/sunrgbd-meta-data) is not a license grant, and the official project page was inaccessible during this audit. |
| ScanNet | **UNVERIFIED for commercial scope** | The [official repository README](https://github.com/ScanNet/ScanNet/blob/master/README.md) says data access requires the ScanNet Terms of Use and distinguishes that data agreement from the code's MIT license. The linked [Terms of Use](http://kaldir.vc.in.tum.de/scannet/ScanNet_TOS.pdf) could not be inspected here; the report correctly leaves commercial permission unverified. |

**Commercial recommendation check:** Objects365 is explicitly academic-purpose
only in its official terms and is not recommended for commercial training in
the research report. The report also avoids recommending the other
rights-unverified sources for commercial use. Do not interpret that as legal
clearance for any source.

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
- **Annotation caveat — INCOMPLETE:** the official facts page describes
  exhaustive boxes for positive boxed labels except group cases. The report
  lists `IsDepiction` and `IsGroupOf` flags but should explicitly require
  filtering or re-annotation where those conflict with P6-1's real-instance
  and one-box-per-instance rules.

## Unsupported, ambiguous, or incomplete findings

1. **Objects365 V2 bottle omission — FAIL:** the published V2 mapping includes
   `Bottle`; update the crosswalk if the research report is revised.
2. **Objects365 table spelling — AMBIGUOUS:** the adapter spells the V2 class
   `Dinning Table` (sic); the report normalizes it to `Dining Table`. This is
   understandable but should be marked as a normalized/typo-bearing source
   label. V1 separately has `dining table`.
3. **Objects365 footwear, luggage, and storage-box mappings — AMBIGUOUS:**
   multiple subtype classes, V2 `Luggage`, and `Storage box` are not exact
   matches for the P6-1 per-object rules. The report generally notes this but
   should keep the qualification adjacent to the table entries.
4. **Open Images realism — UNVERIFIED:** label existence does not prove
   enough indoor examples. Counts by target class after indoor and rights
   filtering remain unmeasured.
5. **Open Images flag handling — INCOMPLETE:** document an explicit policy
   for depictions and group-of boxes before conversion; otherwise its
   annotations can conflict with P6-1.
6. **Objects365 licensing detail — INCOMPLETE:** add the official CC BY 4.0
   license for annotations/website if revising the source report. Do not
   transfer that license to its images.
7. **COCO/ADE20K/SUN RGB-D/ScanNet terms — UNVERIFIED:** the report properly
   avoids claiming commercial clearance, but final source approval remains
   blocked on reviewing their applicable image/data terms.

## Verdict

**Status: GAPS FOUND.** The 20-class order matches the approved specification,
the cable gap is explicit, and the academic-only Objects365 restriction is
handled conservatively. The mapping audit has a concrete Objects365 V2
omission and several source-to-P6 boundary ambiguities. Licensing status for
four other sources remains unverified, and Open Images' ability to meet indoor
per-class targets is not established by aggregate counts.

No P6-3 work is authorized or started by this audit.
