#!/usr/bin/env python3
"""Validate a Canvas New Quiz Builder JSON specification."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


ITEM_TYPES = {
    "multiple_choice",
    "multiple_answer",
    "dropdown",
    "ordering",
    "matching",
    "categorization",
    "essay",
    "file_upload",
    "stimulus",
}
MANUAL_TYPES = {"essay", "file_upload"}
HIGHER_ORDER_ROLES = {"application", "analysis", "evaluation", "transfer", "misconception"}
ROLES = {
    "conceptual",
    "application",
    "analysis",
    "evaluation",
    "transfer",
    "misconception",
    "source_check",
    "recall_support",
    "process_evidence",
    "verification",
    "reflection",
    "artifact",
}
DEPENDENCIES = {"generic", "source_dependent", "activity_dependent", "both"}
SCORING = {"partial", "all_or_nothing"}
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
TOKEN_RE = re.compile(r"\[\[([A-Za-z0-9][A-Za-z0-9_-]*)\]\]")

TOP_FIELDS = {"title", "description", "settings", "items"}
SETTING_FIELDS = {"allowed_attempts", "shuffle_answers", "show_correct_answers"}
BASE_FIELDS = {
    "id",
    "type",
    "title",
    "points",
    "prompt_html",
    "source_locator",
    "assessment_role",
    "source_dependency",
    "parent_stimulus_id",
}
TYPE_FIELDS = {
    "multiple_choice": {"choices"},
    "multiple_answer": {"choices", "scoring"},
    "dropdown": {"blanks"},
    "ordering": {"ordered_items"},
    "matching": {"pairs", "distractors"},
    "categorization": {"categories", "options", "scoring"},
    "essay": set(),
    "file_upload": set(),
    "stimulus": {"content_html", "media", "source_locator"},
}


def load_spec(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"Quiz specification does not exist: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON at line {exc.lineno}, column {exc.colno}: {exc.msg}") from exc
    if not isinstance(data, dict):
        raise ValueError("The quiz specification must be a JSON object.")
    return data


def _text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _list(value: Any) -> bool:
    return isinstance(value, list)


def _unique_ids(entries: Any, location: str, errors: list[str]) -> list[str]:
    if not _list(entries):
        errors.append(f"{location} must be an array.")
        return []
    ids: list[str] = []
    for index, entry in enumerate(entries):
        here = f"{location}[{index}]"
        if not isinstance(entry, dict):
            errors.append(f"{here} must be an object.")
            continue
        ident = entry.get("id")
        if not _text(ident) or not ID_RE.fullmatch(ident):
            errors.append(f"{here}.id must use letters, digits, hyphens, or underscores and start with a letter or digit.")
            continue
        if ident in ids:
            errors.append(f"{location} contains duplicate id '{ident}'.")
        ids.append(ident)
    return ids


def _require_exact_fields(entry: dict[str, Any], allowed: set[str], location: str, errors: list[str]) -> None:
    unexpected = sorted(set(entry) - allowed)
    if unexpected:
        errors.append(f"{location} contains unsupported fields: {', '.join(unexpected)}.")


def _validate_choices(item: dict[str, Any], location: str, multiple: bool, errors: list[str]) -> None:
    choices = item.get("choices")
    ids = _unique_ids(choices, f"{location}.choices", errors)
    if not _list(choices):
        return
    if len(choices) < 2:
        errors.append(f"{location}.choices must contain at least two options.")
    correct = 0
    texts: list[str] = []
    for index, choice in enumerate(choices):
        if not isinstance(choice, dict):
            continue
        here = f"{location}.choices[{index}]"
        _require_exact_fields(choice, {"id", "text", "correct"}, here, errors)
        if not _text(choice.get("text")):
            errors.append(f"{here}.text must be non-empty.")
        else:
            texts.append(choice["text"].strip().casefold())
        if not isinstance(choice.get("correct"), bool):
            errors.append(f"{here}.correct must be true or false.")
        elif choice["correct"]:
            correct += 1
    if len(texts) != len(set(texts)):
        errors.append(f"{location}.choices contains duplicate option text.")
    if multiple:
        if correct < 1 or correct >= len(ids):
            errors.append(f"{location} multiple-answer choices need at least one correct and one incorrect option.")
        if item.get("scoring") not in SCORING:
            errors.append(f"{location}.scoring must be 'partial' or 'all_or_nothing'.")
    elif correct != 1:
        errors.append(f"{location} multiple-choice item must have exactly one correct option; found {correct}.")


def _validate_dropdown(item: dict[str, Any], location: str, errors: list[str], warnings: list[str]) -> None:
    blanks = item.get("blanks")
    blank_ids = _unique_ids(blanks, f"{location}.blanks", errors)
    if not _list(blanks):
        return
    if not 1 <= len(blanks) <= 8:
        warnings.append(f"{location} has {len(blanks)} blanks; 2–5 is usually easier to read and grade proportionately.")
    for index, blank in enumerate(blanks):
        if not isinstance(blank, dict):
            continue
        here = f"{location}.blanks[{index}]"
        _require_exact_fields(blank, {"id", "answer", "options"}, here, errors)
        options = blank.get("options")
        if not _list(options) or not 2 <= len(options) <= 8 or not all(_text(option) for option in options):
            errors.append(f"{here}.options must contain 2–8 non-empty strings.")
            continue
        normalized = [option.strip().casefold() for option in options]
        if len(normalized) != len(set(normalized)):
            errors.append(f"{here}.options contains duplicate text.")
        answer = blank.get("answer")
        if not _text(answer) or answer.strip().casefold() not in normalized:
            errors.append(f"{here}.answer must exactly match one option, ignoring case and outer whitespace.")
    prompt_tokens = TOKEN_RE.findall(item.get("prompt_html", "") if isinstance(item.get("prompt_html"), str) else "")
    if len(prompt_tokens) != len(set(prompt_tokens)):
        errors.append(f"{location}.prompt_html repeats a dropdown token.")
    if set(prompt_tokens) != set(blank_ids):
        errors.append(
            f"{location} dropdown tokens {sorted(set(prompt_tokens))} do not match blank ids {sorted(set(blank_ids))}."
        )


def _validate_ordering(item: dict[str, Any], location: str, errors: list[str], warnings: list[str]) -> None:
    entries = item.get("ordered_items")
    _unique_ids(entries, f"{location}.ordered_items", errors)
    if not _list(entries):
        return
    if len(entries) < 2:
        errors.append(f"{location}.ordered_items must contain at least two entries.")
    if len(entries) > 6:
        warnings.append(f"{location} has more than six all-or-nothing ordering steps.")
    texts: list[str] = []
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            continue
        here = f"{location}.ordered_items[{index}]"
        _require_exact_fields(entry, {"id", "text"}, here, errors)
        if not _text(entry.get("text")):
            errors.append(f"{here}.text must be non-empty.")
        else:
            texts.append(entry["text"].strip().casefold())
    if len(texts) != len(set(texts)):
        errors.append(f"{location}.ordered_items contains duplicate text.")


def _validate_matching(item: dict[str, Any], location: str, errors: list[str]) -> None:
    pairs = item.get("pairs")
    _unique_ids(pairs, f"{location}.pairs", errors)
    if not _list(pairs):
        return
    if len(pairs) < 2:
        errors.append(f"{location}.pairs must contain at least two pairs.")
    answers: list[str] = []
    for index, pair in enumerate(pairs):
        if not isinstance(pair, dict):
            continue
        here = f"{location}.pairs[{index}]"
        _require_exact_fields(pair, {"id", "prompt", "answer"}, here, errors)
        if not _text(pair.get("prompt")) or not _text(pair.get("answer")):
            errors.append(f"{here}.prompt and .answer must be non-empty.")
        else:
            answers.append(pair["answer"].strip().casefold())
    distractors = item.get("distractors", [])
    if not _list(distractors) or not all(_text(value) for value in distractors):
        errors.append(f"{location}.distractors must be an array of non-empty strings.")
        distractors = []
    normalized = answers + [value.strip().casefold() for value in distractors]
    if len(normalized) != len(set(normalized)):
        errors.append(f"{location} matching answers and distractors must have unique text.")


def _validate_categorization(item: dict[str, Any], location: str, errors: list[str]) -> None:
    categories = item.get("categories")
    category_ids = _unique_ids(categories, f"{location}.categories", errors)
    if _list(categories):
        if len(categories) < 2:
            errors.append(f"{location}.categories must contain at least two categories.")
        texts: list[str] = []
        for index, category in enumerate(categories):
            if not isinstance(category, dict):
                continue
            here = f"{location}.categories[{index}]"
            _require_exact_fields(category, {"id", "text"}, here, errors)
            if not _text(category.get("text")):
                errors.append(f"{here}.text must be non-empty.")
            else:
                texts.append(category["text"].strip().casefold())
        if len(texts) != len(set(texts)):
            errors.append(f"{location}.categories contains duplicate category text.")

    options = item.get("options")
    _unique_ids(options, f"{location}.options", errors)
    counts = {ident: 0 for ident in category_ids}
    if _list(options):
        if len(options) < 2:
            errors.append(f"{location}.options must contain at least two options.")
        texts: list[str] = []
        for index, option in enumerate(options):
            if not isinstance(option, dict):
                continue
            here = f"{location}.options[{index}]"
            _require_exact_fields(option, {"id", "text", "category_id"}, here, errors)
            if not _text(option.get("text")):
                errors.append(f"{here}.text must be non-empty.")
            else:
                texts.append(option["text"].strip().casefold())
            category_id = option.get("category_id")
            if category_id is not None and category_id not in category_ids:
                errors.append(f"{here}.category_id '{category_id}' does not identify a category in this item.")
            elif category_id in counts:
                counts[category_id] += 1
        if len(texts) != len(set(texts)):
            errors.append(f"{location}.options contains duplicate option text.")
    for category_id, count in counts.items():
        if count == 0:
            errors.append(f"{location} category '{category_id}' has no keyed options.")
    if item.get("scoring") not in SCORING:
        errors.append(f"{location}.scoring must be 'partial' or 'all_or_nothing'.")


def _validate_stimulus(item: dict[str, Any], location: str, base_dir: Path, errors: list[str]) -> None:
    if not _text(item.get("content_html")) and not item.get("media"):
        errors.append(f"{location} stimulus needs content_html, media, or both.")
    media = item.get("media", [])
    if not _list(media):
        errors.append(f"{location}.media must be an array.")
        return
    for index, entry in enumerate(media):
        here = f"{location}.media[{index}]"
        if not isinstance(entry, dict):
            errors.append(f"{here} must be an object.")
            continue
        _require_exact_fields(entry, {"path", "alt"}, here, errors)
        if not _text(entry.get("path")) or not _text(entry.get("alt")):
            errors.append(f"{here}.path and .alt must be non-empty.")
            continue
        media_path = Path(entry["path"])
        if not media_path.is_absolute():
            media_path = base_dir / media_path
        if not media_path.is_file():
            errors.append(f"{here}.path does not resolve to a file: {media_path}")
        elif media_path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"}:
            errors.append(f"{here}.path must identify a supported image file.")


def validate_spec(data: dict[str, Any], base_dir: Path) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []

    _require_exact_fields(data, TOP_FIELDS, "quiz", errors)
    if not _text(data.get("title")):
        errors.append("quiz.title must be a non-empty string.")
    if "description" in data and not isinstance(data["description"], str):
        errors.append("quiz.description must be a string.")
    settings = data.get("settings", {})
    if not isinstance(settings, dict):
        errors.append("quiz.settings must be an object.")
    else:
        _require_exact_fields(settings, SETTING_FIELDS, "quiz.settings", errors)
        attempts = settings.get("allowed_attempts", 1)
        if not isinstance(attempts, int) or isinstance(attempts, bool) or attempts < 1:
            errors.append("quiz.settings.allowed_attempts must be an integer of 1 or more.")
        for field in ("shuffle_answers", "show_correct_answers"):
            if field in settings and not isinstance(settings[field], bool):
                errors.append(f"quiz.settings.{field} must be true or false.")

    items = data.get("items")
    if not _list(items) or not items:
        errors.append("quiz.items must be a non-empty array.")
        items = []

    item_ids: list[str] = []
    stimulus_positions: dict[str, int] = {}
    child_counts: dict[str, int] = {}
    scored_count = 0
    source_checks = 0
    points_total = 0.0
    auto_graded_count = 0
    manually_graded_count = 0
    auto_graded_points = 0.0
    manually_graded_points = 0.0
    higher_order_count = 0

    for index, item in enumerate(items):
        location = f"items[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{location} must be an object.")
            continue
        item_type = item.get("type")
        allowed_fields = BASE_FIELDS | TYPE_FIELDS.get(item_type, set())
        _require_exact_fields(item, allowed_fields, location, errors)
        ident = item.get("id")
        if not _text(ident) or not ID_RE.fullmatch(ident):
            errors.append(f"{location}.id is invalid.")
        elif ident in item_ids:
            errors.append(f"quiz.items contains duplicate id '{ident}'.")
        else:
            item_ids.append(ident)
        if item_type not in ITEM_TYPES:
            errors.append(f"{location}.type must be one of {sorted(ITEM_TYPES)}.")
            continue
        if not _text(item.get("title")):
            errors.append(f"{location}.title must be non-empty.")

        if item_type == "stimulus":
            if "points" in item:
                errors.append(f"{location} stimulus must not define points.")
            if "parent_stimulus_id" in item:
                errors.append(f"{location} stimulus cannot have a parent_stimulus_id.")
            if _text(ident):
                stimulus_positions[ident] = index
                child_counts[ident] = 0
            _validate_stimulus(item, location, base_dir, errors)
            continue

        scored_count += 1
        points = item.get("points")
        if not isinstance(points, (int, float)) or isinstance(points, bool) or points <= 0:
            errors.append(f"{location}.points must be a number greater than zero.")
        else:
            points_total += float(points)
            if item_type in MANUAL_TYPES:
                manually_graded_points += float(points)
            else:
                auto_graded_points += float(points)
        if item_type in MANUAL_TYPES:
            manually_graded_count += 1
        else:
            auto_graded_count += 1
        for field, allowed in (("assessment_role", ROLES), ("source_dependency", DEPENDENCIES)):
            if item.get(field) not in allowed:
                errors.append(f"{location}.{field} must be one of {sorted(allowed)}.")
        if item.get("assessment_role") == "source_check":
            source_checks += 1
            if item.get("source_dependency") == "generic":
                warnings.append(f"{location} is labeled source_check but source_dependency is generic.")
        if item.get("assessment_role") in HIGHER_ORDER_ROLES:
            higher_order_count += 1
        if not _text(item.get("source_locator")):
            errors.append(f"{location}.source_locator is required for every scored item.")
        if not _text(item.get("prompt_html")):
            errors.append(f"{location}.prompt_html must be non-empty.")

        if item_type == "multiple_choice":
            _validate_choices(item, location, False, errors)
        elif item_type == "multiple_answer":
            _validate_choices(item, location, True, errors)
        elif item_type == "dropdown":
            _validate_dropdown(item, location, errors, warnings)
        elif item_type == "ordering":
            _validate_ordering(item, location, errors, warnings)
        elif item_type == "matching":
            _validate_matching(item, location, errors)
        elif item_type == "categorization":
            _validate_categorization(item, location, errors)

    for index, item in enumerate(items):
        if not isinstance(item, dict) or item.get("type") == "stimulus":
            continue
        parent = item.get("parent_stimulus_id")
        if parent is None:
            continue
        if parent not in stimulus_positions:
            errors.append(f"items[{index}].parent_stimulus_id '{parent}' does not identify a stimulus.")
        elif stimulus_positions[parent] >= index:
            errors.append(f"items[{index}] must appear after its parent stimulus '{parent}'.")
        else:
            child_counts[parent] += 1

    for stimulus_id, count in child_counts.items():
        if count == 0:
            warnings.append(f"Stimulus '{stimulus_id}' has no child questions.")
        elif count == 1:
            warnings.append(f"Stimulus '{stimulus_id}' has only one child; consider embedding it in the question instead.")
        elif count > 4:
            warnings.append(f"Stimulus '{stimulus_id}' has {count} children; check cognitive load and answer leakage.")

    if scored_count and source_checks / scored_count > 0.20:
        warnings.append(
            f"Source-check items are {source_checks}/{scored_count} ({source_checks / scored_count:.0%}); "
            "the default design target is 10–20% unless the instructor requested more."
        )

    if scored_count >= 4 and higher_order_count / scored_count < 0.50:
        warnings.append(
            f"Higher-order items are {higher_order_count}/{scored_count} ({higher_order_count / scored_count:.0%}); "
            "aim for at least half the quiz to assess application, analysis, evaluation, transfer, or misconception repair."
        )

    if manually_graded_count:
        warnings.append(
            "Confirm that each Essay or File Upload item truly requires instructor judgment or artifact inspection "
            "and cannot be represented defensibly as an auto-graded question."
        )

    if scored_count and auto_graded_count == 0:
        warnings.append(
            "Quiz contains no auto-graded items; confirm that every response truly requires manual review."
        )

    return {
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "summary": {
            "items": len(items),
            "scored_items": scored_count,
            "stimuli": len(stimulus_positions),
            "source_checks": source_checks,
            "points": round(points_total, 6),
            "higher_order_items": higher_order_count,
            "auto_graded_items": auto_graded_count,
            "manually_graded_items": manually_graded_count,
            "auto_graded_points": round(auto_graded_points, 6),
            "manually_graded_points": round(manually_graded_points, 6),
        },
    }


def validate_file(path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    data = load_spec(path)
    return data, validate_spec(data, path.resolve().parent)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("quiz_json", type=Path)
    args = parser.parse_args()
    try:
        _, report = validate_file(args.quiz_json)
    except ValueError as exc:
        report = {"valid": False, "errors": [str(exc)], "warnings": [], "summary": {}}
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    sys.exit(main())
