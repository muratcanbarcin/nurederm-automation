"""Validate talepler.json and print an executive summary."""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from process_messages import (
    HANDOFF_CATEGORIES,
    INPUT_PATH,
    OUTPUT_PATH,
    SECURITY_NOTE_PREFIX,
    Category,
)

REQUIRED_KEYS = frozenset({"id", "konu", "devret", "cevap_taslagi", "not"})
EXPECTED_RECORD_COUNT = 15


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
        if keys != REQUIRED_KEYS:
            errors.append(
                f"{label}: key mismatch (missing={sorted(REQUIRED_KEYS - keys)}, "
                f"extra={sorted(keys - REQUIRED_KEYS)})."
            )
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

    if seen_ids != expected_ids:
        errors.append(
            f"Id set mismatch with input (missing={sorted(expected_ids - seen_ids)}, "
            f"unexpected={sorted(seen_ids - expected_ids)})."
        )
    return errors


def print_summary(records: list[dict[str, Any]]) -> None:
    distribution = Counter(record["konu"] for record in records)
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
    print(f"Human handoffs    : {len(handoffs)} (ids: {handoffs})")
    print(f"Security violations: {len(violations)}")
    for record in violations:
        print(f"  id={record['id']}: {record['not']}")
    print("=" * 60)


def main() -> int:
    records = json.loads(OUTPUT_PATH.read_text(encoding="utf-8"))
    expected_ids = {item["id"] for item in json.loads(INPUT_PATH.read_text(encoding="utf-8"))}
    errors = validate(records, expected_ids)
    if errors:
        print("VALIDATION FAILED:")
        for error in errors:
            print(f"  - {error}")
        return 1
    print(f"VALIDATION PASSED: {len(records)} records, schema {sorted(REQUIRED_KEYS)}")
    print_summary(records)
    return 0


if __name__ == "__main__":
    sys.exit(main())
