"""Validate talepler.json (and talepler.csv when present) and print an executive summary."""

from __future__ import annotations

import csv
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from process_messages import (
    CATEGORY_PRIORITY,
    CSV_COLUMNS,
    CSV_PATH,
    HANDOFF_CATEGORIES,
    INPUT_PATH,
    OUTPUT_PATH,
    PRIORITY_RANK,
    SECURITY_NOTE_PREFIX,
    Category,
    Priority,
)

REQUIRED_KEYS = frozenset({"id", "konu", "devret", "cevap_taslagi", "not"})
# Optional so that legacy talepler.json files produced before priority scoring still validate.
OPTIONAL_KEYS = frozenset({"oncelik"})
EXPECTED_RECORD_COUNT = 15
UTF8_BOM = b"\xef\xbb\xbf"


def validate_priority(label: str, record: dict[str, Any]) -> list[str]:
    valid_priorities = {priority.value for priority in Priority}
    if record["oncelik"] not in valid_priorities:
        return [f"{label}: invalid priority '{record['oncelik']}'."]

    errors: list[str] = []
    priority = Priority(record["oncelik"])
    if record["konu"] in {category.value for category in Category}:
        baseline = CATEGORY_PRIORITY[Category(record["konu"])]
        if PRIORITY_RANK[priority] < PRIORITY_RANK[baseline]:
            errors.append(
                f"{label}: category '{record['konu']}' requires at least priority '{baseline.value}'."
            )
    if str(record["not"]).startswith(SECURITY_NOTE_PREFIX) and priority is not Priority.HIGH:
        errors.append(f"{label}: security violation requires priority '{Priority.HIGH.value}'.")
    return errors


def validate(records: Any, expected_ids: set[int]) -> list[str]:
    errors: list[str] = []
    if not isinstance(records, list):
        return ["Root element must be a JSON array."]
    if len(records) != EXPECTED_RECORD_COUNT:
        errors.append(f"Expected {EXPECTED_RECORD_COUNT} records, found {len(records)}.")

    valid_categories = {category.value for category in Category}
    handoff_values = {category.value for category in HANDOFF_CATEGORIES}
    seen_ids: set[int] = set()

    for index, record in enumerate(records):
        label = f"record[{index}]"
        if not isinstance(record, dict):
            errors.append(f"{label}: not an object.")
            continue
        keys = set(record)
        missing = REQUIRED_KEYS - keys
        extra = keys - REQUIRED_KEYS - OPTIONAL_KEYS
        if missing or extra:
            errors.append(f"{label}: key mismatch (missing={sorted(missing)}, extra={sorted(extra)}).")
            continue
        if not isinstance(record["id"], int):
            errors.append(f"{label}: 'id' must be an integer.")
        elif record["id"] in seen_ids:
            errors.append(f"{label}: duplicate id {record['id']}.")
        else:
            seen_ids.add(record["id"])
        if record["konu"] not in valid_categories:
            errors.append(f"{label}: invalid category '{record['konu']}'.")
        if not isinstance(record["devret"], bool):
            errors.append(f"{label}: 'devret' must be a boolean.")
        if not isinstance(record["cevap_taslagi"], str) or not record["cevap_taslagi"].strip():
            errors.append(f"{label}: 'cevap_taslagi' must be a non-empty string.")
        if not isinstance(record["not"], str) or not record["not"].strip():
            errors.append(f"{label}: 'not' must be a non-empty string.")
        if record["konu"] in handoff_values and record["devret"] is not True:
            errors.append(f"{label}: category '{record['konu']}' requires devret=true.")
        if str(record["not"]).startswith(SECURITY_NOTE_PREFIX) and record["devret"] is not True:
            errors.append(f"{label}: security violation must be handed off.")
        if "oncelik" in record:
            errors.extend(validate_priority(label, record))

    if seen_ids != expected_ids:
        errors.append(
            f"Id set mismatch with input (missing={sorted(expected_ids - seen_ids)}, "
            f"unexpected={sorted(seen_ids - expected_ids)})."
        )
    return errors


def validate_csv(
    path: Path, records: list[dict[str, Any]], messages: list[dict[str, Any]]
) -> list[str]:
    """Check that talepler.csv is UTF-8 BOM encoded and mirrors talepler.json row by row."""
    raw = path.read_bytes()
    if not raw.startswith(UTF8_BOM):
        return [f"{path.name}: missing UTF-8 BOM."]
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.reader(handle))
    if not rows or tuple(rows[0]) != CSV_COLUMNS:
        return [f"{path.name}: header must be {list(CSV_COLUMNS)}, found {rows[0] if rows else []}."]

    messages_by_id = {message["id"]: message for message in messages}
    expected_rows = [
        [
            str(record["id"]),
            str(messages_by_id.get(record["id"], {}).get("kanal", "")),
            str(messages_by_id.get(record["id"], {}).get("musteri_id", "")),
            record["konu"],
            str(record.get("oncelik", "")),
            "true" if record["devret"] else "false",
            record["cevap_taslagi"],
            record["not"],
        ]
        for record in records
    ]
    body = rows[1:]
    if len(body) != len(expected_rows):
        return [f"{path.name}: expected {len(expected_rows)} data rows, found {len(body)}."]
    return [
        f"{path.name}: row {index + 1} (id={expected[0]}) does not match talepler.json."
        for index, (actual, expected) in enumerate(zip(body, expected_rows))
        if actual != expected
    ]


def print_summary(records: list[dict[str, Any]]) -> None:
    distribution = Counter(record["konu"] for record in records)
    priorities = Counter(record.get("oncelik") for record in records)
    handoffs = [record["id"] for record in records if record["devret"]]
    violations = [
        record for record in records if record["not"].startswith(SECURITY_NOTE_PREFIX)
    ]

    print("=" * 60)
    print("EXECUTIVE SUMMARY - talepler.json")
    print("=" * 60)
    print(f"Total records     : {len(records)}")
    print("Category distribution:")
    for category in Category:
        print(f"  {category.value:<16} {distribution.get(category.value, 0):>3}")
    if any(priorities.keys() - {None}):
        print("Priority distribution:")
        for priority in Priority:
            ids = [record["id"] for record in records if record.get("oncelik") == priority.value]
            print(f"  {priority.value:<16} {priorities.get(priority.value, 0):>3} (ids: {ids})")
    print(f"Human handoffs    : {len(handoffs)} (ids: {handoffs})")
    print(f"Security violations: {len(violations)}")
    for record in violations:
        print(f"  id={record['id']}: {record['not']}")
    print("=" * 60)


def main() -> int:
    records = json.loads(OUTPUT_PATH.read_text(encoding="utf-8"))
    messages = json.loads(INPUT_PATH.read_text(encoding="utf-8"))
    expected_ids = {item["id"] for item in messages}
    errors = validate(records, expected_ids)
    if not errors and CSV_PATH.exists():
        errors = validate_csv(CSV_PATH, records, messages)
    if errors:
        print("VALIDATION FAILED:")
        for error in errors:
            print(f"  - {error}")
        return 1
    schema = sorted(REQUIRED_KEYS | (OPTIONAL_KEYS & set(records[0])) if records else REQUIRED_KEYS)
    print(f"VALIDATION PASSED: {len(records)} records, schema {schema}")
    if CSV_PATH.exists():
        print(f"CSV EXPORT PASSED: {CSV_PATH.name} (UTF-8 BOM, {len(records)} rows, columns {list(CSV_COLUMNS)})")
    print_summary(records)
    return 0


if __name__ == "__main__":
    sys.exit(main())
