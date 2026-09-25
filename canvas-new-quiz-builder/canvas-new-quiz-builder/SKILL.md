---
name: canvas-new-quiz-builder
description: Create, transform, validate, and package Canvas New Quizzes from educational materials in any accessible format, including readings, documents, slides, websites, videos, transcripts, diagrams, images, activities, and existing question banks. Prioritize higher-order, source-grounded questions and automatic grading wherever a defensible fixed key is possible; use focused Essay or File Upload questions only when the required evidence genuinely needs instructor review. Generate a validated Canvas-importable QTI ZIP.
---

# Canvas New Quiz Builder

Create instructionally useful Canvas New Quizzes and deterministic Canvas-flavored QTI 1.2 packages. Emphasize application, analysis, comparison, diagnosis, misconception repair, evaluation, and transfer. Use automatic grading whenever the source supports a defensible key; do not force subjective evidence into an artificial fixed answer.

## Inputs and scope

Accept educational material in any accessible format, including PDFs, documents, slides, webpages, transcripts, videos, diagrams, images, instructor notes, activities, labs, and existing question banks. Combine multiple sources when supplied.

Inspect every source enough to identify its objectives, organization, distinctive examples, important evidence, diagrams, misconceptions, and usable locators. Never invent a source claim, expected result, answer key, or missing activity content. If a required source or key is absent, request it or provide a clearly incomplete blueprint with placeholders when the instructor asks to proceed.

Follow a requested question count or point total when provided. Otherwise infer an appropriate scope from the material and course context, and ask only when the missing choice would materially change the assessment.

## Core workflow

1. Inspect all supplied material and identify the intended audience, learning objectives, important distinctions, misconceptions, source-dependent evidence, and opportunities for transfer.
2. Read [assessment-design.md](references/assessment-design.md). Create a compact blueprint before drafting questions.
3. Read [new-quizzes-question-types.md](references/new-quizzes-question-types.md). Choose each format because it fits the evidence required, not merely because the source contains convenient signal words.
4. Apply the auto-grading funnel: use a supported auto-graded type whenever one defensible key exists; otherwise use Essay or File Upload only for evidence that genuinely requires instructor review.
5. Draft the quiz as JSON conforming to [quiz-schema.json](assets/quiz-schema.json). Keep instructor-only information out of student-facing prompts.
6. Run `python3 <skill-dir>/scripts/validate_quiz.py QUIZ.json`. Correct every error. Review each warning and either fix it or consciously accept it.
7. Run `python3 <skill-dir>/scripts/build_qti.py QUIZ.json OUTPUT.zip`. This validates the JSON before creating a Canvas-flavored QTI 1.2 package.
8. Run `python3 <skill-dir>/scripts/validate_qti.py OUTPUT.zip`. Do not deliver a package that fails.
9. Provide the QTI ZIP, JSON specification, compact blueprint, and only unresolved QA warnings. Tell the instructor to import into an unpublished New Quiz and preview it before assigning it.

## Auto-grading funnel

For every learning objective or required piece of evidence:

1. Identify what a successful student response must demonstrate.
2. Determine whether the supplied material supports one defensible fixed key.
3. If yes, choose the strongest fitting auto-graded type: stimulus-linked selection, categorization, dropdown, matching, multiple answer, ordering, or multiple choice.
4. If no, use Essay for focused reasoning, judgment, explanation, reflection, or transfer that must be evaluated by an instructor.
5. Use File Upload only when the artifact itself must be inspected, such as a screenshot, log, spreadsheet, report, project file, or completed product.

Do not use a manually graded type merely because it is easier to draft. Conversely, do not convert authentic judgment or creative work into a fake fixed-answer key merely to increase the auto-graded percentage.

## Assessment priorities

- Begin with learning objectives and source-grounded evidence rather than isolated facts.
- Prefer a short source excerpt, image, table, diagram, course-specific case, flawed explanation, or paired responses followed by 2–4 linked questions when the material supports it.
- Favor questions that ask students to apply, distinguish, interpret, analyze, diagnose, evaluate, repair a misconception, or transfer learning to a new situation.
- Use categorization for non-overlapping conceptual distinctions; dropdown cloze for connected explanations; scenario-based multiple choice for judgment among plausible actions; matching for exact relationships; multiple answer for several independently meaningful claims; and ordering only when order is genuinely causal, procedural, chronological, or scalar.
- Preserve useful misconceptions from an existing bank. Remove silly distractors and grammatical giveaways.
- Make questions independent enough that one answer does not reveal another.
- Use course-specific examples and source language when pedagogically relevant, but avoid testing accidental wording.
- Permit occasional reading or viewing verification items. Label them `source_check`, ground them in a meaningful detail, and normally keep them to 10–20% of scored items unless the instructor requests more.
- Use Essay and File Upload only after exhausting valid auto-graded formats.

## Source grounding

Give every scored item a `source_locator` such as a page and section, slide number, timestamp, transcript segment, diagram label, existing-bank item, or stable webpage section. Use `source_locator: "Instructor-created synthesis"` only for a clearly labeled synthesis supported by supplied material.

For a changing webpage, place the necessary excerpt or screenshot in a stimulus so students see the assessed version. Do not rely on an unpreserved page whose content may change.

## Blueprint requirements

Include:

- Objective or concept coverage.
- Planned item types and point values.
- Stimulus groupings and child items.
- Assessment role: `conceptual`, `application`, `analysis`, `evaluation`, `transfer`, `misconception`, `source_check`, `recall_support`, or an appropriate manual-evidence role.
- Source dependency: `generic`, `source_dependent`, `activity_dependent`, or `both`.
- Automatically graded versus manually graded item and point totals.
- Any deliberate use of all-or-nothing scoring.

Aim for a strong majority of application, analysis, evaluation, transfer, conceptual distinction, and misconception-repair items. Recall-support and source-check items may be useful but should not dominate by default.

## Quality gates

Before building QTI, confirm all of the following:

- Every auto-graded answer is supported by the cited source or locator.
- Every auto-graded item has one defensible key.
- Every Essay or File Upload question collects evidence that cannot be graded validly with a supported fixed-answer type.
- Essay prompts request focused, gradable evidence rather than generic reflection.
- File Upload prompts specify exactly what artifact to upload and remove unnecessary personal or sensitive information.
- Categorization labels are mutually exclusive for every scored option; distractors belong to none.
- Ordering has one defensible sequence with no ties; remember that Canvas grades it all-or-nothing.
- Dropdown blanks use visible tokens such as `[[model_type]]`; each token has one response definition, and the surrounding grammar does not reveal the answer.
- Multiple-answer wording states or makes clear that more than one answer may be correct.
- Matching does not rely on duplicate answer text.
- Stimulus children reference an existing stimulus and appear after it.
- No answer is exposed in the prompt, title, feedback, or another item.
- Difficulty comes from meaningful thinking or source engagement, not obscure wording.
- Images include useful alt text and are legible at quiz scale.
- Point totals and partial-credit choices are intentional.

## QTI boundaries

Use Canvas New Quizzes only. The bundled builder implements multiple choice, multiple answer, matching, ordering, categorization, dropdown fill-in-the-blank, text or image stimuli with linked questions, Essay, and File Upload.

Read [qti-implementation.md](references/qti-implementation.md) only when changing or debugging QTI generation. Do not hand-edit generated XML for normal quiz creation. Rebuild from the JSON specification instead.

The importer may not preserve every Canvas setting. After import, verify question types, keys, stimulus grouping, point totals, feedback visibility, partial-credit settings, and the behavior of Essay and File Upload questions before publishing.

## Runtime and portability

The bundled scripts require Python 3.10 or newer and use only the Python standard library. They make no network requests. Run them only in an environment that permits local file access and command execution. If the environment cannot run the scripts, provide the draft JSON and blueprint, explain that QTI packaging and validation remain incomplete, and do not claim that the final ZIP was generated.

## Output discipline

Keep the review output lean:

1. Blueprint table.
2. Downloadable `.zip` and `.json` files.
3. Warnings only; omit lengthy self-justification for routine design choices.

When the instructor asks to review questions before packaging, stop after the JSON draft and a readable question review. Generate the QTI only after approval or requested revisions.
