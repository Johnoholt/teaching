#!/usr/bin/env python3
"""Build a Canvas New Quizzes QTI 1.2 ZIP from validated quiz JSON."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import random
import re
import shutil
import sys
import tempfile
import uuid
import zipfile
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from validate_quiz import validate_file


QTI_NS = "http://www.imsglobal.org/xsd/ims_qtiasiv1p2"
XSI_NS = "http://www.w3.org/2001/XMLSchema-instance"
MANIFEST_NS = "http://www.imsglobal.org/xsd/imsccv1p1/imscp_v1p1"
IMSMD_NS = "http://www.imsglobal.org/xsd/imsmd_v1p2"
CANVAS_NS = "http://canvas.instructure.com/xsd/cccv1p0"


def stable_hex(label: str) -> str:
    return hashlib.md5(label.encode("utf-8")).hexdigest()


def stable_uuid(label: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"canvas-new-quiz-builder:{label}"))


def canonical_fingerprint(spec: dict[str, Any]) -> str:
    payload = json.dumps(spec, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def sub(parent: ET.Element, tag: str, text: str | None = None, **attrs: str) -> ET.Element:
    node = ET.SubElement(parent, tag, attrs)
    if text is not None:
        node.text = text
    return node


def qti_sub(parent: ET.Element, tag: str, text: str | None = None, **attrs: str) -> ET.Element:
    return sub(parent, f"{{{QTI_NS}}}{tag}", text, **attrs)


def add_metadata(
    item_node: ET.Element,
    question_type: str,
    points: float,
    fingerprint: str,
    logical_id: str,
    answer_ids: list[str] | None = None,
    parent_stimulus: str | None = None,
    extra: list[tuple[str, str]] | None = None,
    answer_ids_as_json: bool = False,
) -> None:
    itemmetadata = qti_sub(item_node, "itemmetadata")
    qtimetadata = qti_sub(itemmetadata, "qtimetadata")
    fields: list[tuple[str, str]] = [
        ("question_type", question_type),
        ("points_possible", f"{points:g}"),
        (
            "original_answer_ids",
            json.dumps(answer_ids or []) if answer_ids_as_json else ",".join(answer_ids or []),
        ),
        ("assessment_question_identifierref", stable_hex(f"{fingerprint}:question:{logical_id}")),
    ]
    if parent_stimulus:
        fields.append(("parent_stimulus_item_ident", parent_stimulus))
    fields.append(("calculator_type", "none"))
    fields.extend(extra or [])
    for label, value in fields:
        field = qti_sub(qtimetadata, "qtimetadatafield")
        qti_sub(field, "fieldlabel", label)
        qti_sub(field, "fieldentry", value)


def prompt_material(parent: ET.Element, prompt_html: str, orientation: str | None = None) -> None:
    attrs = {"orientation": orientation} if orientation else {}
    material = qti_sub(parent, "material", **attrs)
    qti_sub(material, "mattext", prompt_html, texttype="text/html")


def plain_material(parent: ET.Element, text: str, texttype: str = "text/plain") -> None:
    material = qti_sub(parent, "material")
    qti_sub(material, "mattext", text, texttype=texttype)


def choice_label(
    parent: ET.Element,
    ident: str,
    text: str,
    *,
    dropdown: bool = False,
    position: int | None = None,
    texttype: str = "text/html",
) -> None:
    attrs = {"ident": ident}
    if dropdown:
        attrs.update({"scoring_algorithm": "Equivalence", "answer_type": "dropdown"})
        if position is not None:
            attrs["position"] = str(position)
    label = qti_sub(parent, "response_label", **attrs)
    plain_material(label, text, texttype)


def score_outcomes(parent: ET.Element) -> None:
    outcomes = qti_sub(parent, "outcomes")
    qti_sub(outcomes, "decvar", maxvalue="100", minvalue="0", varname="SCORE", vartype="Decimal")


def set_score(condition: ET.Element, value: float, action: str = "Set") -> None:
    qti_sub(condition, "setvar", f"{value:.6f}".rstrip("0").rstrip("."), action=action, varname="SCORE")


def no_continue(parent: ET.Element, tag: str) -> ET.Element:
    node = qti_sub(parent, tag)
    node.set("continue", "No")
    return node


def item_ident(fingerprint: str, logical_id: str) -> str:
    return stable_hex(f"{fingerprint}:item:{logical_id}")


def nested_ident(fingerprint: str, item_id: str, kind: str, logical_id: str) -> str:
    return stable_uuid(f"{fingerprint}:{item_id}:{kind}:{logical_id}")


def parent_ident(item: dict[str, Any], id_map: dict[str, str]) -> str | None:
    parent = item.get("parent_stimulus_id")
    return id_map[parent] if parent else None


def build_multiple_choice(
    section: ET.Element, item: dict[str, Any], fingerprint: str, id_map: dict[str, str]
) -> None:
    node = qti_sub(section, "item", ident=id_map[item["id"]], title=item["title"])
    answers = [
        (nested_ident(fingerprint, item["id"], "choice", choice["id"]), choice["text"], choice["correct"])
        for choice in item["choices"]
    ]
    add_metadata(
        node,
        "multiple_choice_question",
        item["points"],
        fingerprint,
        item["id"],
        [ident for ident, _, _ in answers],
        parent_ident(item, id_map),
    )
    presentation = qti_sub(node, "presentation")
    prompt_material(presentation, item["prompt_html"])
    response = qti_sub(presentation, "response_lid", ident="response1", rcardinality="Single")
    render = qti_sub(response, "render_choice")
    for ident, text, _ in answers:
        choice_label(render, ident, text)
    processing = qti_sub(node, "resprocessing")
    score_outcomes(processing)
    condition = no_continue(processing, "respcondition")
    conditionvar = qti_sub(condition, "conditionvar")
    correct_id = next(ident for ident, _, correct in answers if correct)
    qti_sub(conditionvar, "varequal", correct_id, respident="response1")
    set_score(condition, 100)


def build_multiple_answer(
    section: ET.Element, item: dict[str, Any], fingerprint: str, id_map: dict[str, str]
) -> None:
    node = qti_sub(section, "item", ident=id_map[item["id"]], title=item["title"])
    answers = [
        (nested_ident(fingerprint, item["id"], "choice", choice["id"]), choice["text"], choice["correct"])
        for choice in item["choices"]
    ]
    algorithm = "PartialScore" if item["scoring"] == "partial" else "AllOrNothing"
    add_metadata(
        node,
        "multiple_answers_question",
        item["points"],
        fingerprint,
        item["id"],
        [ident for ident, _, _ in answers],
        parent_ident(item, id_map),
        [("scoring_algorithm", algorithm)],
    )
    presentation = qti_sub(node, "presentation")
    prompt_material(presentation, item["prompt_html"])
    response = qti_sub(presentation, "response_lid", ident="response1", rcardinality="Multiple")
    render = qti_sub(response, "render_choice")
    for ident, text, _ in answers:
        choice_label(render, ident, text)
    processing = qti_sub(node, "resprocessing")
    score_outcomes(processing)
    condition = no_continue(processing, "respcondition")
    conditionvar = qti_sub(condition, "conditionvar")
    and_node = qti_sub(conditionvar, "and")
    for ident, _, correct in answers:
        if correct:
            qti_sub(and_node, "varequal", ident, respident="response1")
        else:
            not_node = qti_sub(and_node, "not")
            qti_sub(not_node, "varequal", ident, respident="response1")
    set_score(condition, 100)


def build_dropdown(
    section: ET.Element, item: dict[str, Any], fingerprint: str, id_map: dict[str, str]
) -> None:
    node = qti_sub(section, "item", ident=id_map[item["id"]], title=item["title"])
    prompt = item["prompt_html"]
    prepared: list[tuple[str, dict[str, Any], list[tuple[str, str]]]] = []
    all_answer_ids: list[str] = []
    for blank in item["blanks"]:
        blank_uuid = nested_ident(fingerprint, item["id"], "blank", blank["id"])
        prompt = prompt.replace(f"[[{blank['id']}]]", f"[{blank_uuid}]")
        options = [
            (nested_ident(fingerprint, item["id"], f"blank-{blank['id']}", str(index)), option)
            for index, option in enumerate(blank["options"])
        ]
        all_answer_ids.extend(ident for ident, _ in options)
        prepared.append((blank_uuid, blank, options))
    add_metadata(
        node,
        "fill_in_multiple_blanks_question",
        item["points"],
        fingerprint,
        item["id"],
        all_answer_ids,
        parent_ident(item, id_map),
        answer_ids_as_json=True,
    )
    presentation = qti_sub(node, "presentation")
    prompt_material(presentation, prompt)
    correct: list[tuple[str, str]] = []
    for blank_uuid, blank, options in prepared:
        response_id = f"response_{blank_uuid}"
        response = qti_sub(presentation, "response_lid", ident=response_id)
        plain_material(response, blank["answer"])
        render = qti_sub(response, "render_choice")
        correct_id = ""
        for position, (ident, option) in enumerate(options, start=1):
            choice_label(render, ident, option, dropdown=True, position=position, texttype="text/plain")
            if option.strip().casefold() == blank["answer"].strip().casefold():
                correct_id = ident
        correct.append((response_id, correct_id))
    processing = qti_sub(node, "resprocessing")
    score_outcomes(processing)
    share = 100 / len(correct)
    for response_id, correct_id in correct:
        condition = qti_sub(processing, "respcondition")
        conditionvar = qti_sub(condition, "conditionvar")
        qti_sub(conditionvar, "varequal", correct_id, respident=response_id)
        set_score(condition, share, action="Add")


def build_ordering(
    section: ET.Element, item: dict[str, Any], fingerprint: str, id_map: dict[str, str]
) -> None:
    node = qti_sub(section, "item", ident=id_map[item["id"]], title=item["title"])
    ordered = [
        (nested_ident(fingerprint, item["id"], "order", entry["id"]), entry["text"])
        for entry in item["ordered_items"]
    ]
    add_metadata(
        node,
        "ordering_question",
        item["points"],
        fingerprint,
        item["id"],
        [ident for ident, _ in ordered],
        parent_ident(item, id_map),
    )
    presentation = qti_sub(node, "presentation")
    prompt_material(presentation, item["prompt_html"])
    response = qti_sub(presentation, "response_lid", ident="response1", rcardinality="Ordered")
    extension = qti_sub(response, "render_extension")
    render = qti_sub(extension, "ims_render_object", shuffle="No")
    flow = qti_sub(render, "flow_label")
    display = ordered.copy()
    random.Random(int(stable_hex(f"{fingerprint}:{item['id']}:display"), 16)).shuffle(display)
    if display == ordered and len(display) > 1:
        display[0], display[1] = display[1], display[0]
    for ident, text in display:
        choice_label(flow, ident, text)
    processing = qti_sub(node, "resprocessing")
    outcomes = qti_sub(processing, "outcomes")
    qti_sub(outcomes, "decvar", defaultval="1", varname="ORDERSCORE", vartype="Integer")
    condition = no_continue(processing, "respcondition")
    conditionvar = qti_sub(condition, "conditionvar")
    for ident, _ in ordered:
        qti_sub(conditionvar, "varequal", ident, respident="response1")
    set_score(condition, 100)


def build_matching(
    section: ET.Element, item: dict[str, Any], fingerprint: str, id_map: dict[str, str]
) -> None:
    node = qti_sub(section, "item", ident=id_map[item["id"]], title=item["title"])
    pairs = [
        (
            nested_ident(fingerprint, item["id"], "left", pair["id"]),
            nested_ident(fingerprint, item["id"], "right", pair["id"]),
            pair["prompt"],
            pair["answer"],
        )
        for pair in item["pairs"]
    ]
    distractors = [
        (nested_ident(fingerprint, item["id"], "distractor", str(index)), text)
        for index, text in enumerate(item.get("distractors", []))
    ]
    right_options = [(right_id, answer) for _, right_id, _, answer in pairs] + distractors
    add_metadata(
        node,
        "matching_question",
        item["points"],
        fingerprint,
        item["id"],
        [right_id for _, right_id, _, _ in pairs],
        parent_ident(item, id_map),
        [("scoring_algorithm", "PartialDeep")],
    )
    presentation = qti_sub(node, "presentation")
    prompt_material(presentation, item["prompt_html"])
    for left_id, _, prompt, _ in pairs:
        response_id = f"response_{left_id}"
        response = qti_sub(presentation, "response_lid", ident=response_id)
        plain_material(response, prompt)
        render = qti_sub(response, "render_choice")
        for right_id, answer in right_options:
            choice_label(render, right_id, answer, texttype="text/plain")
    processing = qti_sub(node, "resprocessing")
    score_outcomes(processing)
    share = 100 / len(pairs)
    for left_id, right_id, _, _ in pairs:
        condition = qti_sub(processing, "respcondition")
        conditionvar = qti_sub(condition, "conditionvar")
        qti_sub(conditionvar, "varequal", right_id, respident=f"response_{left_id}")
        set_score(condition, share, action="Add")


def build_categorization(
    section: ET.Element, item: dict[str, Any], fingerprint: str, id_map: dict[str, str]
) -> None:
    node = qti_sub(section, "item", ident=id_map[item["id"]], title=item["title"])
    categories = [
        (nested_ident(fingerprint, item["id"], "category", category["id"]), category["id"], category["text"])
        for category in item["categories"]
    ]
    options = [
        (
            nested_ident(fingerprint, item["id"], "option", option["id"]),
            option["text"],
            option["category_id"],
        )
        for option in item["options"]
    ]
    score_method = "partial_credit" if item["scoring"] == "partial" else "all_or_nothing"
    add_metadata(
        node,
        "categorization_question",
        item["points"],
        fingerprint,
        item["id"],
        [],
        parent_ident(item, id_map),
        [("score_method", score_method)],
    )
    presentation = qti_sub(node, "presentation")
    prompt_material(presentation, item["prompt_html"])
    category_id_map = {logical_id: generated_id for generated_id, logical_id, _ in categories}
    for generated_category_id, _, category_text in categories:
        response = qti_sub(
            presentation, "response_lid", ident=generated_category_id, rcardinality="Multiple"
        )
        plain_material(response, category_text)
        render = qti_sub(response, "render_choice")
        for option_id, option_text, _ in options:
            choice_label(render, option_id, option_text, texttype="text/plain")
    processing = qti_sub(node, "resprocessing")
    score_outcomes(processing)
    share = 100 / len(categories)
    for generated_category_id, logical_category_id, _ in categories:
        condition = qti_sub(processing, "respcondition")
        conditionvar = qti_sub(condition, "conditionvar")
        for option_id, _, logical_target in options:
            if logical_target == logical_category_id:
                qti_sub(conditionvar, "varequal", option_id, respident=generated_category_id)
        set_score(condition, share, action="Add")


def build_essay(
    section: ET.Element, item: dict[str, Any], fingerprint: str, id_map: dict[str, str]
) -> None:
    node = qti_sub(section, "item", ident=id_map[item["id"]], title=item["title"])
    add_metadata(
        node,
        "essay_question",
        item["points"],
        fingerprint,
        item["id"],
        [],
        parent_ident(item, id_map),
    )
    presentation = qti_sub(node, "presentation")
    prompt_material(presentation, item["prompt_html"])
    response = qti_sub(presentation, "response_str", ident="response1", rcardinality="Single")
    render = qti_sub(response, "render_fib")
    qti_sub(render, "response_label", ident="answer1", rshuffle="No")
    processing = qti_sub(node, "resprocessing")
    score_outcomes(processing)
    condition = no_continue(processing, "respcondition")
    conditionvar = qti_sub(condition, "conditionvar")
    qti_sub(conditionvar, "other")


def build_file_upload(
    section: ET.Element, item: dict[str, Any], fingerprint: str, id_map: dict[str, str]
) -> None:
    node = qti_sub(section, "item", ident=id_map[item["id"]], title=item["title"])
    add_metadata(
        node,
        "file_upload_question",
        item["points"],
        fingerprint,
        item["id"],
        [],
        parent_ident(item, id_map),
    )
    presentation = qti_sub(node, "presentation")
    prompt_material(presentation, item["prompt_html"])
    processing = qti_sub(node, "resprocessing")
    score_outcomes(processing)


def safe_media_name(source: Path, fingerprint: str, item_id: str, index: int, used: set[str]) -> str:
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", source.stem).strip("-._") or "media"
    suffix = re.sub(r"[^A-Za-z0-9.]+", "", source.suffix.lower()) or ".bin"
    candidate = f"{stem}{suffix}"
    if candidate.casefold() in used:
        candidate = f"{stem}-{stable_hex(f'{fingerprint}:{item_id}:{index}')[:8]}{suffix}"
    used.add(candidate.casefold())
    return candidate


def build_stimulus(
    section: ET.Element,
    item: dict[str, Any],
    fingerprint: str,
    id_map: dict[str, str],
    json_dir: Path,
    build_dir: Path,
    media_records: list[str],
    used_media_names: set[str],
) -> None:
    node = qti_sub(section, "item", ident=id_map[item["id"]], title=item["title"], instructions="")
    add_metadata(
        node,
        "text_only_question",
        0,
        fingerprint,
        item["id"],
        [],
        extra=[("source_url", ""), ("passage", "false")],
    )
    content_parts: list[str] = []
    for index, media in enumerate(item.get("media", [])):
        source = Path(media["path"])
        if not source.is_absolute():
            source = json_dir / source
        name = safe_media_name(source, fingerprint, item["id"], index, used_media_names)
        archive_path = f"Uploaded Media/{name}"
        destination = build_dir / archive_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        media_records.append(archive_path)
        content_parts.append(
            f'<p><img src="$IMS-CC-FILEBASE$/{html.escape(archive_path, quote=True)}" '
            f'alt="{html.escape(media["alt"], quote=True)}"></p>'
        )
    content_parts.append(item.get("content_html", ""))
    presentation = qti_sub(node, "presentation")
    prompt_material(presentation, "".join(content_parts), orientation="left")


BUILDERS = {
    "multiple_choice": build_multiple_choice,
    "multiple_answer": build_multiple_answer,
    "dropdown": build_dropdown,
    "ordering": build_ordering,
    "matching": build_matching,
    "categorization": build_categorization,
    "essay": build_essay,
    "file_upload": build_file_upload,
}


def write_assessment(
    spec: dict[str, Any],
    fingerprint: str,
    assessment_id: str,
    assessment_dir: Path,
    json_dir: Path,
    build_dir: Path,
    media_records: list[str],
) -> None:
    ET.register_namespace("", QTI_NS)
    ET.register_namespace("xsi", XSI_NS)
    root = ET.Element(
        f"{{{QTI_NS}}}questestinterop",
        {f"{{{XSI_NS}}}schemaLocation": f"{QTI_NS} http://www.imsglobal.org/xsd/ims_qtiasiv1p2p1.xsd"},
    )
    assessment = qti_sub(root, "assessment", ident=assessment_id, title=spec["title"])
    qtimetadata = qti_sub(assessment, "qtimetadata")
    field = qti_sub(qtimetadata, "qtimetadatafield")
    qti_sub(field, "fieldlabel", "cc_maxattempts")
    qti_sub(field, "fieldentry", str(spec.get("settings", {}).get("allowed_attempts", 1)))
    section = qti_sub(assessment, "section", ident="root_section")
    id_map = {item["id"]: item_ident(fingerprint, item["id"]) for item in spec["items"]}
    used_media_names: set[str] = set()
    for item in spec["items"]:
        if item["type"] == "stimulus":
            build_stimulus(
                section,
                item,
                fingerprint,
                id_map,
                json_dir,
                build_dir,
                media_records,
                used_media_names,
            )
        else:
            BUILDERS[item["type"]](section, item, fingerprint, id_map)
    ET.indent(root, space="  ")
    ET.ElementTree(root).write(
        assessment_dir / f"{assessment_id}.xml", encoding="utf-8", xml_declaration=True
    )


def write_meta(spec: dict[str, Any], fingerprint: str, assessment_id: str, assessment_dir: Path) -> None:
    ET.register_namespace("", CANVAS_NS)
    ET.register_namespace("xsi", XSI_NS)
    root = ET.Element(
        f"{{{CANVAS_NS}}}quiz",
        {
            "identifier": assessment_id,
            f"{{{XSI_NS}}}schemaLocation": f"{CANVAS_NS} https://canvas.instructure.com/xsd/cccv1p0.xsd",
        },
    )
    settings = spec.get("settings", {})
    points = sum(float(item.get("points", 0)) for item in spec["items"] if item["type"] != "stimulus")
    show_correct = str(settings.get("show_correct_answers", True)).lower()
    values = [
        ("title", spec["title"]),
        ("description", spec.get("description", "")),
        ("shuffle_questions", "false"),
        ("shuffle_answers", str(settings.get("shuffle_answers", False)).lower()),
        ("calculator_type", "none"),
        ("scoring_policy", "keep_highest"),
        ("quiz_type", "assignment"),
        ("points_possible", f"{points:g}"),
        ("require_lockdown_browser", "false"),
        ("show_correct_answers", show_correct),
        ("anonymous_submissions", "false"),
        ("allowed_attempts", str(settings.get("allowed_attempts", 1))),
        ("one_question_at_a_time", "false"),
        ("available", "false"),
        ("result_view_restricted", "false"),
        ("display_items", "true"),
        ("display_item_feedback", "true"),
        ("display_item_response", "true"),
        ("display_points_awarded", "true"),
        ("display_points_possible", "true"),
        ("display_item_correct_answer", show_correct),
        ("display_item_response_correctness", "true"),
        ("display_item_response_qualifier", "always"),
        ("display_item_response_correctness_qualifier", "always"),
    ]
    for tag, value in values:
        sub(root, f"{{{CANVAS_NS}}}{tag}", value)
    assignment = sub(
        root,
        f"{{{CANVAS_NS}}}assignment",
        identifier=stable_hex(f"{fingerprint}:assignment"),
    )
    assignment_values = [
        ("title", spec["title"]),
        ("module_locked", "false"),
        ("workflow_state", "unpublished"),
        ("quiz_identifierref", assessment_id),
        ("has_group_category", "false"),
        ("points_possible", f"{points:g}"),
        ("grading_type", "points"),
        ("all_day", "false"),
        ("submission_types", "online_quiz"),
        ("position", "1"),
        ("turnitin_enabled", "false"),
        ("peer_reviews", "false"),
        ("automatic_peer_reviews", "false"),
        ("anonymous_peer_reviews", "false"),
        ("grade_group_students_individually", "false"),
        ("freeze_on_copy", "false"),
        ("omit_from_final_grade", "false"),
        ("only_visible_to_overrides", "false"),
        ("post_to_sis", "false"),
        ("moderated_grading", "false"),
    ]
    for tag, value in assignment_values:
        sub(assignment, f"{{{CANVAS_NS}}}{tag}", value)
    ET.indent(root, space="  ")
    ET.ElementTree(root).write(assessment_dir / "assessment_meta.xml", encoding="utf-8", xml_declaration=True)


def write_manifest(
    spec: dict[str, Any],
    fingerprint: str,
    assessment_id: str,
    meta_id: str,
    build_dir: Path,
    media_records: list[str],
) -> None:
    ET.register_namespace("", MANIFEST_NS)
    ET.register_namespace("imsmd", IMSMD_NS)
    ET.register_namespace("xsi", XSI_NS)
    root = ET.Element(
        f"{{{MANIFEST_NS}}}manifest",
        {
            "identifier": stable_hex(f"{fingerprint}:manifest"),
            f"{{{XSI_NS}}}schemaLocation": (
                f"{MANIFEST_NS} http://www.imsglobal.org/xsd/imscp_v1p1.xsd "
                "http://ltsc.ieee.org/xsd/imsccv1p1/LOM/resource "
                "http://www.imsglobal.org/profile/cc/ccv1p1/LOM/ccv1p1_lomresource_v1p0.xsd "
                f"{IMSMD_NS} http://www.imsglobal.org/xsd/imsmd_v1p2p2.xsd"
            ),
        },
    )
    metadata_node = sub(root, f"{{{MANIFEST_NS}}}metadata")
    sub(metadata_node, f"{{{MANIFEST_NS}}}schema", "IMS Content")
    sub(metadata_node, f"{{{MANIFEST_NS}}}schemaversion", "1.1.3")
    lom = sub(metadata_node, f"{{{IMSMD_NS}}}lom")
    general = sub(lom, f"{{{IMSMD_NS}}}general")
    title = sub(general, f"{{{IMSMD_NS}}}title")
    sub(title, f"{{{IMSMD_NS}}}string", spec["title"])
    sub(root, f"{{{MANIFEST_NS}}}organizations")
    resources = sub(root, f"{{{MANIFEST_NS}}}resources")
    assessment_resource = sub(
        resources, f"{{{MANIFEST_NS}}}resource", identifier=assessment_id, type="imsqti_xmlv1p2"
    )
    sub(assessment_resource, f"{{{MANIFEST_NS}}}file", href=f"{assessment_id}/{assessment_id}.xml")
    sub(assessment_resource, f"{{{MANIFEST_NS}}}dependency", identifierref=meta_id)
    meta_resource = sub(
        resources,
        f"{{{MANIFEST_NS}}}resource",
        identifier=meta_id,
        type="associatedcontent/imscc_xmlv1p1/learning-application-resource",
        href=f"{assessment_id}/assessment_meta.xml",
    )
    sub(meta_resource, f"{{{MANIFEST_NS}}}file", href=f"{assessment_id}/assessment_meta.xml")
    for archive_path in media_records:
        resource = sub(
            resources,
            f"{{{MANIFEST_NS}}}resource",
            identifier=stable_hex(f"{fingerprint}:media:{archive_path}"),
            type="webcontent",
            href=archive_path,
        )
        sub(resource, f"{{{MANIFEST_NS}}}file", href=archive_path)
    ET.indent(root, space="  ")
    ET.ElementTree(root).write(build_dir / "imsmanifest.xml", encoding="utf-8", xml_declaration=True)


def build_package(spec_path: Path, output_path: Path) -> dict[str, Any]:
    spec, report = validate_file(spec_path)
    if not report["valid"]:
        raise ValueError("Quiz JSON failed validation:\n- " + "\n- ".join(report["errors"]))
    fingerprint = canonical_fingerprint(spec)
    assessment_id = stable_hex(f"{fingerprint}:assessment")
    meta_id = stable_hex(f"{fingerprint}:meta")
    output_path = output_path.resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="canvas-qti-") as temp_name:
        build_dir = Path(temp_name)
        assessment_dir = build_dir / assessment_id
        assessment_dir.mkdir()
        media_records: list[str] = []
        write_assessment(
            spec,
            fingerprint,
            assessment_id,
            assessment_dir,
            spec_path.resolve().parent,
            build_dir,
            media_records,
        )
        write_meta(spec, fingerprint, assessment_id, assessment_dir)
        write_manifest(spec, fingerprint, assessment_id, meta_id, build_dir, media_records)
        with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(build_dir.rglob("*")):
                if path.is_file():
                    archive.write(path, path.relative_to(build_dir).as_posix())
    with zipfile.ZipFile(output_path) as archive:
        corrupt = archive.testzip()
        if corrupt:
            raise ValueError(f"Corrupt ZIP member after build: {corrupt}")
    return {
        "output": str(output_path),
        "assessment_id": assessment_id,
        "items": len(spec["items"]),
        "points": report["summary"]["points"],
        "warnings": report["warnings"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("quiz_json", type=Path)
    parser.add_argument("output_zip", type=Path)
    args = parser.parse_args()
    try:
        result = build_package(args.quiz_json, args.output_zip)
    except (OSError, ValueError) as exc:
        print(json.dumps({"built": False, "error": str(exc)}, indent=2, ensure_ascii=False))
        return 1
    print(json.dumps({"built": True, **result}, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
