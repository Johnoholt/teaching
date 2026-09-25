# Canvas New Quizzes question types

## Contents

1. Grading boundary
2. Selection hierarchy
3. Supported JSON types
4. Scoring and design cautions
5. Stimulus behavior

## Grading boundary

Use supported auto-graded types whenever the supplied material supports one defensible fixed key. Use Essay or File Upload only when the evidence genuinely requires instructor judgment or artifact inspection.

Do not choose a manually graded type merely because it is easier to draft. Do not force judgment, critique, reflection, creative production, or authentic artifacts into artificial fixed keys merely to maximize automatic grading.

## Selection hierarchy

Choose the smallest format that validly measures the objective.

| Priority | Design | Best use |
| --- | --- | --- |
| Highest | Stimulus with 2–4 linked questions | Source interpretation, comparison, error diagnosis, application, evaluation |
| High | Categorization | Distinguishing scenarios, claims, evidence, errors, or examples |
| High | Dropdown cloze | Completing a connected explanation or repairing a misconception |
| High | Scenario multiple choice | Selecting the best explanation, interpretation, diagnosis, evidence, or action |
| Medium-high | Matching | Connecting situations to concepts, evidence, explanations, or corrections |
| Medium-high | Multiple answer | Judging several independently meaningful claims, causes, or actions |
| Selective | Ordering | Genuine causal, procedural, chronological, or scalar sequence |
| Supporting | Recall or source check | Retrieval practice or verification of reading and viewing |
| Manual fallback | Essay | Focused reasoning, critique, judgment, explanation, reflection, or transfer |
| Manual fallback | File Upload | Screenshots, logs, data files, reports, calculations, designs, or final products |

## Supported JSON types

- `multiple_choice`
- `multiple_answer`
- `dropdown`
- `ordering`
- `matching`
- `categorization`
- `essay`
- `file_upload`
- `stimulus`

Use `parent_stimulus_id` on a scored item to attach it to a preceding stimulus.

### Multiple choice

Provide `choices`, each with `id`, `text`, and `correct`. Exactly one must be correct. Prefer scenarios, interpretation, diagnosis, or evidence selection over isolated recall.

### Multiple answer

Provide `choices` with at least one correct and one incorrect option. Set `scoring` to `partial` or `all_or_nothing`. The generated QTI contains an exact key and Canvas metadata; review imported partial-credit behavior.

### Dropdown

Write `prompt_html` with visible named tokens such as `[[claim_source]]`. Provide one `blanks` entry for each token with a unique `id`, correct `answer`, and 2–8 `options`. The builder converts each token to Canvas's internal blank identifier.

### Ordering

Provide `ordered_items` in the correct order as objects with unique `id` and `text` fields. The builder changes the display order deterministically. Canvas Ordering is all-or-nothing; do not promise partial credit.

### Matching

Provide `pairs`, each with `id`, `prompt`, and `answer`. Optional `distractors` is an array of unused right-side answer strings. Keep every answer and distractor text unique.

### Categorization

Provide `categories` as unique `id` and `text` objects. Provide `options` as unique `id`, `text`, and `category_id` objects. A distractor uses `category_id: null`. Set `scoring` to `partial` or `all_or_nothing`. Category boundaries must be non-overlapping.

### Essay

Provide the common scored-item fields; no answer key is required. Ask for concise evidence that can be graded against a clear expectation. Prefer prompts such as “Identify the strongest piece of evidence and explain why it outweighs the alternative” over generic prompts such as “What did you learn?”

### File Upload

Provide the common scored-item fields; no answer key is required. State exactly what the student must upload, any required view or contents, and any privacy cleanup. Use it for evidence that Canvas must retain as a file, not as a substitute for an answer that could be auto-graded.

### Stimulus

Provide `content_html` and optional image `media`. A media entry has `path` and useful `alt`. Resolve relative paths from the JSON file. The builder copies media into the QTI package and prepends it to the stimulus. Stimuli carry zero points.

## Scoring and design cautions

- Ordering is all-or-nothing.
- Dropdown blanks receive equal fractions of the question's points in the generated key.
- Matching receives equal fractions per pair in the generated key.
- Categorization partial credit counts category decisions; distractors also matter in Canvas's scoring model.
- Multiple-answer and categorization scoring choices are written to Canvas metadata, but grading behavior can evolve. Inspect the imported quiz before publishing.
- A stimulus is a container, not a graded item.
- Essay and File Upload are manually graded. Their points count in the quiz total but never receive an auto-grading key.
- Basic Essay and File Upload mappings are written to QTI. Canvas-specific options such as word limits, Rich Content Editor settings, allowed extensions, and upload-count limits may require adjustment after import.

## Stimulus behavior

Place a stimulus before all of its children in `items`. Give each child the stimulus's logical `id` in `parent_stimulus_id`. Keep child questions intelligible only with the stimulus when source dependence is intentional, but do not create clues across children.
