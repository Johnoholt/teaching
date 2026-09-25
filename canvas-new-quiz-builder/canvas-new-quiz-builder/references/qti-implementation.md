# QTI implementation notes

## Contents

1. Package structure
2. Canvas mappings
3. Media
4. Validation
5. Boundaries

## Package structure

The builder creates a Canvas-flavored QTI 1.2/Common Cartridge ZIP:

```text
imsmanifest.xml
<assessment-id>/
  <assessment-id>.xml
  assessment_meta.xml
Uploaded Media/
  <optional files>
```

Identifiers are deterministic hashes or UUIDs derived from the canonical quiz JSON and logical item IDs. Rebuilding the same JSON produces stable identifiers.

## Canvas mappings

| JSON type | Canvas QTI metadata |
| --- | --- |
| `multiple_choice` | `multiple_choice_question` |
| `multiple_answer` | `multiple_answers_question` |
| `dropdown` | `fill_in_multiple_blanks_question` with `answer_type="dropdown"` |
| `ordering` | `ordering_question` |
| `matching` | `matching_question` |
| `categorization` | `categorization_question` |
| `essay` | `essay_question` with one `response_str` and no score key |
| `file_upload` | `file_upload_question` with no response or score key |
| `stimulus` | zero-point `text_only_question` |

Stimulus children include `parent_stimulus_item_ident` pointing to the generated QTI identifier of the parent.

Dropdown prompts use Canvas's bracketed internal blank UUIDs, one `response_lid` per blank, and a JSON array in `original_answer_ids`.

## Media

Stimulus media are copied to `Uploaded Media/`. HTML uses `$IMS-CC-FILEBASE$/Uploaded Media/<filename>`, and the manifest declares each file as a `webcontent` resource. Duplicate filenames receive a deterministic suffix.

## Validation

`validate_quiz.py` checks schema and instructional invariants before packaging. `validate_qti.py` then checks:

- ZIP integrity and safe archive paths.
- XML well-formedness.
- Manifest file resolution.
- Unique item and response identifiers.
- Scoring references to offered responses.
- Dropdown placeholder-to-response matching.
- Stimulus-parent linkage.
- Declared and calculated point totals.
- ZIP integrity.

## Boundaries

The auto-graded formats were round-trip verified against Canvas New Quizzes. Essay and File Upload use Canvas-compatible QTI 1.2 mappings and remain manually graded; verify both types after import before use. The package does not encode New Quizzes-only Essay or File Upload options such as word limits, Rich Content Editor settings, allowed extensions, or upload-count limits. Adjust those in Canvas when needed.

The format does not create Classic Quizzes, item banks, hot spots, formula questions, outcomes, rubrics, accommodations, or direct Canvas API changes. Import into an unpublished quiz and preview before use.
