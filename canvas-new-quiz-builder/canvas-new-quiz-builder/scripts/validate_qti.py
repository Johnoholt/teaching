#!/usr/bin/env python3
"""Validate a generated Canvas New Quizzes QTI 1.2 ZIP package."""

from __future__ import annotations

import argparse
import json
import posixpath
import re
import sys
import zipfile
from pathlib import PurePosixPath
from typing import Any
from xml.etree import ElementTree as ET


QTI_NS = "http://www.imsglobal.org/xsd/ims_qtiasiv1p2"
MANIFEST_NS = "http://www.imsglobal.org/xsd/imsccv1p1/imscp_v1p1"
CANVAS_NS = "http://canvas.instructure.com/xsd/cccv1p0"
SUPPORTED_TYPES = {
    "multiple_choice_question",
    "multiple_answers_question",
    "fill_in_multiple_blanks_question",
    "ordering_question",
    "matching_question",
    "categorization_question",
    "essay_question",
    "file_upload_question",
    "text_only_question",
}
MANUAL_TYPES = {"essay_question", "file_upload_question"}
MEDIA_RE = re.compile(r"\$IMS-CC-FILEBASE\$/([^\"'<>]+)")
BLANK_RE = re.compile(r"\[([0-9a-f-]{36})\]")


def _metadata(item: ET.Element, ns: dict[str, str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for field in item.findall("q:itemmetadata/q:qtimetadata/q:qtimetadatafield", ns):
        label = field.findtext("q:fieldlabel", default="", namespaces=ns)
        value = field.findtext("q:fieldentry", default="", namespaces=ns)
        if label:
            result[label] = value
    return result


def _safe_member(name: str) -> bool:
    path = PurePosixPath(name)
    return not path.is_absolute() and ".." not in path.parts and "" not in path.parts


def validate_package(path: str) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    summary: dict[str, Any] = {}
    try:
        archive = zipfile.ZipFile(path)
    except (FileNotFoundError, zipfile.BadZipFile) as exc:
        return {"valid": False, "errors": [str(exc)], "warnings": [], "summary": {}}

    with archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            errors.append("ZIP contains duplicate member names.")
        unsafe = [name for name in names if not _safe_member(name)]
        if unsafe:
            errors.append(f"ZIP contains unsafe member paths: {unsafe}.")
        corrupt = archive.testzip()
        if corrupt:
            errors.append(f"ZIP integrity check failed at {corrupt}.")
        if "imsmanifest.xml" not in names:
            errors.append("Package is missing imsmanifest.xml at the ZIP root.")
            return {"valid": False, "errors": errors, "warnings": warnings, "summary": summary}

        try:
            manifest = ET.fromstring(archive.read("imsmanifest.xml"))
        except ET.ParseError as exc:
            errors.append(f"imsmanifest.xml is not well formed: {exc}.")
            return {"valid": False, "errors": errors, "warnings": warnings, "summary": summary}
        mns = {"m": MANIFEST_NS}
        declared_files = [node.get("href", "") for node in manifest.findall(".//m:file", mns)]
        for href in declared_files:
            if href not in names:
                errors.append(f"Manifest file reference does not resolve: {href}.")

        resource_ids: set[str] = set()
        qti_paths: list[str] = []
        meta_paths: list[str] = []
        for resource in manifest.findall(".//m:resource", mns):
            ident = resource.get("identifier", "")
            if not ident:
                errors.append("Manifest resource is missing an identifier.")
            elif ident in resource_ids:
                errors.append(f"Manifest resource identifier is duplicated: {ident}.")
            resource_ids.add(ident)
            resource_type = resource.get("type", "")
            files = [node.get("href", "") for node in resource.findall("m:file", mns)]
            if resource_type == "imsqti_xmlv1p2":
                qti_paths.extend(files)
            if resource_type == "associatedcontent/imscc_xmlv1p1/learning-application-resource":
                meta_paths.extend(files)
            for dependency in resource.findall("m:dependency", mns):
                target = dependency.get("identifierref", "")
                if target and target not in {
                    candidate.get("identifier", "") for candidate in manifest.findall(".//m:resource", mns)
                }:
                    errors.append(f"Manifest dependency does not resolve: {target}.")
        if len(qti_paths) != 1:
            errors.append(f"Expected one QTI assessment XML file; found {qti_paths}.")
        if len(meta_paths) != 1:
            errors.append(f"Expected one Canvas assessment_meta.xml file; found {meta_paths}.")
        if errors and (not qti_paths or not meta_paths):
            return {"valid": False, "errors": errors, "warnings": warnings, "summary": summary}

        try:
            qti_root = ET.fromstring(archive.read(qti_paths[0]))
            meta_root = ET.fromstring(archive.read(meta_paths[0]))
        except (KeyError, ET.ParseError) as exc:
            errors.append(f"Assessment XML could not be parsed: {exc}.")
            return {"valid": False, "errors": errors, "warnings": warnings, "summary": summary}

        qns = {"q": QTI_NS}
        cns = {"c": CANVAS_NS}
        items = qti_root.findall(".//q:item", qns)
        item_ids = [item.get("ident", "") for item in items]
        if not items:
            errors.append("QTI assessment contains no items.")
        if any(not ident for ident in item_ids):
            errors.append("At least one QTI item is missing ident.")
        if len(item_ids) != len(set(item_ids)):
            errors.append("QTI item identifiers are not unique.")

        stimulus_ids: set[str] = set()
        child_links: list[tuple[str, str]] = []
        type_counts: dict[str, int] = {}
        points_total = 0.0
        auto_graded_points = 0.0
        manually_graded_points = 0.0
        for index, item in enumerate(items):
            title = item.get("title", f"item {index + 1}")
            metadata = _metadata(item, qns)
            question_type = metadata.get("question_type", "")
            type_counts[question_type] = type_counts.get(question_type, 0) + 1
            if question_type not in SUPPORTED_TYPES:
                errors.append(f"{title}: unsupported or missing question_type '{question_type}'.")
            try:
                points = float(metadata.get("points_possible", ""))
            except ValueError:
                errors.append(f"{title}: points_possible is not numeric.")
                points = 0
            if question_type == "text_only_question":
                if points != 0:
                    errors.append(f"{title}: stimulus must have zero points.")
                stimulus_ids.add(item.get("ident", ""))
            else:
                if points <= 0:
                    errors.append(f"{title}: scored item must have positive points.")
                points_total += points
                if question_type in MANUAL_TYPES:
                    manually_graded_points += points
                else:
                    auto_graded_points += points
            parent = metadata.get("parent_stimulus_item_ident")
            if parent:
                child_links.append((title, parent))

            responses = item.findall("q:presentation/q:response_lid", qns)
            string_responses = item.findall("q:presentation/q:response_str", qns)
            response_map = {response.get("ident", ""): response for response in responses}
            if len(response_map) != len(responses) or "" in response_map:
                errors.append(f"{title}: response identifiers are missing or duplicated.")
            for varequal in item.findall("q:resprocessing/q:respcondition/q:conditionvar//q:varequal", qns):
                response_id = varequal.get("respident", "")
                if response_id not in response_map:
                    errors.append(f"{title}: scoring refers to missing response '{response_id}'.")
                    continue
                offered = {
                    label.get("ident", "")
                    for label in response_map[response_id].findall(".//q:response_label", qns)
                }
                if (varequal.text or "") not in offered:
                    errors.append(f"{title}: scoring key is not offered by response '{response_id}'.")

            prompt = item.findtext("q:presentation/q:material/q:mattext", default="", namespaces=qns)
            for media_path in MEDIA_RE.findall(prompt):
                normalized = posixpath.normpath(media_path)
                if normalized not in names:
                    errors.append(f"{title}: embedded media does not resolve: {media_path}.")

            if question_type == "multiple_choice_question":
                if len(responses) != 1 or responses[0].get("rcardinality") != "Single":
                    errors.append(f"{title}: multiple choice must have one Single response.")
            elif question_type == "multiple_answers_question":
                if len(responses) != 1 or responses[0].get("rcardinality") != "Multiple":
                    errors.append(f"{title}: multiple answer must have one Multiple response.")
            elif question_type == "fill_in_multiple_blanks_question":
                blanks = set(BLANK_RE.findall(prompt))
                response_blanks = {
                    response_id.removeprefix("response_") for response_id in response_map
                }
                if blanks != response_blanks:
                    errors.append(f"{title}: prompt blanks do not match response blocks.")
                for response in responses:
                    options = response.findall(".//q:response_label", qns)
                    if not options or any(option.get("answer_type") != "dropdown" for option in options):
                        errors.append(f"{title}: every blank option must be marked as a dropdown.")
                try:
                    original_ids = json.loads(metadata.get("original_answer_ids", ""))
                    offered_ids = [
                        label.get("ident", "")
                        for response in responses
                        for label in response.findall(".//q:response_label", qns)
                    ]
                    if set(original_ids) != set(offered_ids):
                        errors.append(f"{title}: original_answer_ids does not match dropdown options.")
                except json.JSONDecodeError:
                    errors.append(f"{title}: original_answer_ids must be a JSON array for dropdown items.")
            elif question_type == "ordering_question":
                if len(responses) != 1 or responses[0].get("rcardinality") != "Ordered":
                    errors.append(f"{title}: ordering must have one Ordered response.")
            elif question_type == "matching_question":
                if len(responses) < 2:
                    errors.append(f"{title}: matching requires at least two response rows.")
            elif question_type == "categorization_question":
                if len(responses) < 2 or any(response.get("rcardinality") != "Multiple" for response in responses):
                    errors.append(f"{title}: categorization requires at least two Multiple category responses.")
                if metadata.get("score_method") not in {"partial_credit", "all_or_nothing"}:
                    errors.append(f"{title}: categorization score_method is invalid.")
            elif question_type == "essay_question":
                if responses or len(string_responses) != 1:
                    errors.append(f"{title}: essay requires exactly one string response and no choice response.")
                elif string_responses[0].get("rcardinality") != "Single":
                    errors.append(f"{title}: essay string response must have Single cardinality.")
                elif string_responses[0].find("q:render_fib/q:response_label", qns) is None:
                    errors.append(f"{title}: essay string response is missing its response label.")
                if item.findall("q:resprocessing//q:setvar", qns):
                    errors.append(f"{title}: essay must not contain an auto-grading score key.")
            elif question_type == "file_upload_question":
                if responses or string_responses:
                    errors.append(f"{title}: file upload must not contain a text or choice response block.")
                if item.findall("q:resprocessing//q:setvar", qns):
                    errors.append(f"{title}: file upload must not contain an auto-grading score key.")

        for title, parent in child_links:
            if parent not in stimulus_ids:
                errors.append(f"{title}: parent stimulus identifier does not resolve: {parent}.")

        declared_text = meta_root.findtext("c:points_possible", default="", namespaces=cns)
        try:
            declared_points = float(declared_text)
        except ValueError:
            errors.append("assessment_meta.xml points_possible is not numeric.")
            declared_points = 0
        if abs(declared_points - points_total) > 1e-6:
            errors.append(
                f"Point total mismatch: QTI items total {points_total:g}, metadata declares {declared_points:g}."
            )
        assignment_points = meta_root.findtext(
            "c:assignment/c:points_possible", default="", namespaces=cns
        )
        try:
            if abs(float(assignment_points) - points_total) > 1e-6:
                errors.append("Assignment point total does not match QTI item total.")
        except ValueError:
            errors.append("Assignment points_possible is not numeric.")

        undeclared_media = [
            name for name in names if name.startswith("Uploaded Media/") and name not in declared_files
        ]
        if undeclared_media:
            errors.append(f"Media files are not declared in the manifest: {undeclared_media}.")

        summary = {
            "zip_members": len(names),
            "items": len(items),
            "stimuli": len(stimulus_ids),
            "stimulus_children": len(child_links),
            "points": round(points_total, 6),
            "auto_graded_points": round(auto_graded_points, 6),
            "manually_graded_points": round(manually_graded_points, 6),
            "question_types": type_counts,
        }

    return {"valid": not errors, "errors": errors, "warnings": warnings, "summary": summary}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("qti_zip")
    args = parser.parse_args()
    report = validate_package(args.qti_zip)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    sys.exit(main())
