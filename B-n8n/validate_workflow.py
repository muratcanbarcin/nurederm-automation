"""Validate B-n8n/workflow.json structurally and behaviourally.

Structural checks run offline. Unless --offline is given, the embedded Code-node
JavaScript is also syntax-checked and executed end-to-end against the live
target site via tests/simulate_pipeline.js (requires Node.js 18+).
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
WORKFLOW_PATH = ROOT / "workflow.json"
SIMULATION_SCRIPT = ROOT / "tests" / "simulate_pipeline.js"

REQUIRED_NODE_TYPES: dict[str, str] = {
    "n8n-nodes-base.scheduleTrigger": "Schedule Trigger",
    "n8n-nodes-base.httpRequest": "HTTP Request",
    "n8n-nodes-base.code": "Code (extraction / normalization)",
    "n8n-nodes-base.if": "IF (stop condition / validation)",
    "n8n-nodes-base.googleSheets": "Google Sheets (persistence)",
    "n8n-nodes-base.filter": "Filter (change detection)",
    "n8n-nodes-base.telegram": "Telegram (notification)",
    "n8n-nodes-base.stopAndError": "Stop and Error (abort)",
    "n8n-nodes-base.errorTrigger": "Error Trigger (global safety net)",
}
NODE_REQUIRED_KEYS = ("id", "name", "type", "typeVersion", "position", "parameters")


class Report:
    def __init__(self) -> None:
        self.failures: list[str] = []
        self.passes = 0

    def check(self, condition: bool, message: str) -> None:
        if condition:
            self.passes += 1
            print(f"  [PASS] {message}")
        else:
            self.failures.append(message)
            print(f"  [FAIL] {message}")


def build_graph(connections: dict[str, Any]) -> dict[str, dict[int, list[str]]]:
    graph: dict[str, dict[int, list[str]]] = defaultdict(dict)
    for source, outputs in connections.items():
        for output_index, targets in enumerate(outputs.get("main", [])):
            graph[source][output_index] = [t["node"] for t in targets or []]
    return graph


def successors(graph: dict[str, dict[int, list[str]]], name: str) -> list[str]:
    return [target for targets in graph.get(name, {}).values() for target in targets]


def reachable(graph: dict[str, dict[int, list[str]]], start: str) -> set[str]:
    seen: set[str] = set()
    stack = [start]
    while stack:
        current = stack.pop()
        for target in successors(graph, current):
            if target not in seen:
                seen.add(target)
                stack.append(target)
    return seen


def validate_structure(workflow: dict[str, Any], report: Report) -> None:
    print("\nStructure")
    nodes: list[dict[str, Any]] = workflow.get("nodes", [])
    connections: dict[str, Any] = workflow.get("connections", {})
    by_name = {n["name"]: n for n in nodes}
    by_type: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for n in nodes:
        by_type[n["type"]].append(n)

    report.check(isinstance(workflow.get("name"), str) and bool(workflow["name"]), "workflow has a name")
    report.check(workflow.get("settings", {}).get("executionOrder") == "v1", "settings.executionOrder is v1")
    report.check(
        all(all(key in n for key in NODE_REQUIRED_KEYS) for n in nodes),
        f"every node defines {', '.join(NODE_REQUIRED_KEYS)}",
    )
    report.check(len(by_name) == len(nodes), "node names are unique")
    report.check(len({n["id"] for n in nodes}) == len(nodes), "node ids are unique")

    dangling = [
        f"{source} -> {target['node']}"
        for source, outputs in connections.items()
        for targets in outputs.get("main", [])
        for target in targets or []
        if source not in by_name or target["node"] not in by_name
    ]
    report.check(not dangling, f"all connections reference existing nodes {dangling or ''}".strip())

    print("\nMandatory nodes")
    for node_type, label in REQUIRED_NODE_TYPES.items():
        report.check(bool(by_type.get(node_type)), f"{label} present ({node_type})")

    graph = build_graph(connections)
    functional = [n for n in nodes if n["type"] not in {"n8n-nodes-base.stickyNote"}]
    triggers = {n["name"] for n in functional if n["type"].endswith("Trigger")}
    covered = set(triggers)
    for trigger in triggers:
        covered |= reachable(graph, trigger)
    orphans = sorted(n["name"] for n in functional if n["name"] not in covered)
    report.check(not orphans, f"every functional node is reachable from a trigger {orphans or ''}".strip())

    print("\nSchedule")
    schedule = by_type["n8n-nodes-base.scheduleTrigger"][0] if by_type.get("n8n-nodes-base.scheduleTrigger") else {}
    intervals = schedule.get("parameters", {}).get("rule", {}).get("interval", [])
    report.check(
        any(i.get("field") == "cronExpression" and i.get("expression") == "0 9 * * *" for i in intervals),
        "cron expression is '0 9 * * *'",
    )
    report.check(workflow.get("settings", {}).get("timezone") == "Europe/Istanbul", "timezone pinned to Europe/Istanbul")

    print("\nPagination")
    http = by_name.get("Fetch Laptop Page", {})
    url = http.get("parameters", {}).get("url", "")
    report.check(
        url == "=https://webscraper.io/test-sites/e-commerce/static/computers/laptops?page={{ $json.page }}",
        "HTTP URL paginates with ?page={{ $json.page }}",
    )
    report.check("Fetch Laptop Page" in reachable(graph, "Fetch Laptop Page"), "pagination loop cycles back to the HTTP node")
    report.check(
        graph.get("Has Next Page?", {}).get(1) == ["Finalize Snapshot"],
        "loop exit (Has Next Page? = false) proceeds to Finalize Snapshot",
    )
    parse_code = by_name.get("Parse & Normalize Page", {}).get("parameters", {}).get("jsCode", "")
    next_conditions = by_name.get("Has Next Page?", {}).get("parameters", {}).get("conditions", {}).get("conditions", [])
    report.check(
        'rel="next"' in parse_code and any("maxPages" in str(c.get("rightValue", "")) for c in next_conditions),
        'stop condition uses rel="next" detection plus maxPages bound',
    )
    report.check("parseFloat" in parse_code and "[^0-9.,-]" in parse_code, "price sanitization strips currency and parses float")

    print("\nError handling")
    report.check(http.get("onError") == "continueErrorOutput", "HTTP node routes transport errors to an error output")
    report.check(http.get("retryOnFail") is True and int(http.get("maxTries", 0)) >= 2, "HTTP node retries before failing")
    response_opts = http.get("parameters", {}).get("options", {}).get("response", {}).get("response", {})
    report.check(response_opts.get("neverError") is True and response_opts.get("fullResponse") is True,
                 "HTTP node exposes statusCode for 4xx/5xx evaluation")
    failure_entries = {
        "HTTP transport error": graph.get("Fetch Laptop Page", {}).get(1, []),
        "non-2xx status": graph.get("HTTP Status OK?", {}).get(1, []),
        "zero products / parse failure": graph.get("Page Healthy?", {}).get(1, []),
    }
    for label, targets in failure_entries.items():
        report.check(targets == ["Build Failure Payload"], f"{label} routes to Build Failure Payload")
    failure_path = reachable(graph, "Build Failure Payload")
    report.check({"Send Failure Alert", "Abort Execution"} <= failure_path, "failure branch alerts then aborts")
    report.check(by_name.get("Send Failure Alert", {}).get("onError") == "continueRegularOutput",
                 "abort still runs if the failure alert itself fails")
    report.check("Send Critical Alert" in reachable(graph, "On Unhandled Workflow Error"), "Error Trigger sends a critical alert")

    print("\nPersistence and change detection")
    main_path = reachable(graph, "Daily 09:00 Trigger")
    append = by_name.get("Append Snapshot to History", {})
    report.check(append.get("parameters", {}).get("operation") == "append", "history sheet uses append operation")
    schema_ids = [c["id"] for c in append.get("parameters", {}).get("columns", {}).get("schema", [])]
    report.check({"scraped_at", "product_id", "price", "change_type"} <= set(schema_ids), "history schema holds timestamp/price/diff columns")
    report.check("$now.toISO()" in by_name.get("Finalize Snapshot", {}).get("parameters", {}).get("jsCode", ""),
                 "snapshot rows are stamped with $now ISO timestamp")
    report.check(by_name.get("Read Price History", {}).get("alwaysOutputData") is True,
                 "history read tolerates an empty sheet (alwaysOutputData)")
    report.check({"Read Price History", "Detect Price Changes", "Only Changed or New", "Send Price Change Alert"} <= main_path,
                 "read -> diff -> filter -> alert chain is wired")
    alert = by_name.get("Send Price Change Alert", {}).get("parameters", {})
    report.check(alert.get("additionalFields", {}).get("parse_mode") == "Markdown", "price alert is sent as Markdown")


def syntax_check_code_nodes(workflow: dict[str, Any], report: Report, node_bin: str) -> None:
    print("\nCode node syntax (node --check)")
    for n in workflow["nodes"]:
        if n["type"] != "n8n-nodes-base.code":
            continue
        wrapped = f"async function __n8nCodeNode($, $input, $now, $execution) {{\n{n['parameters']['jsCode']}\n}}\n"
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as handle:
            handle.write(wrapped)
            temp_path = Path(handle.name)
        try:
            result = subprocess.run([node_bin, "--check", str(temp_path)], capture_output=True, text=True)
        finally:
            temp_path.unlink(missing_ok=True)
        report.check(result.returncode == 0, f"{n['name']} {result.stderr.strip()}".strip())


def run_simulation(report: Report, node_bin: str) -> None:
    print("\nLive end-to-end simulation (tests/simulate_pipeline.js)")
    result = subprocess.run([node_bin, str(SIMULATION_SCRIPT)], capture_output=True, text=True, encoding="utf-8")
    print("\n".join(f"    {line}" for line in (result.stdout + result.stderr).strip().splitlines()))
    report.check(result.returncode == 0, "code nodes scrape, sanitize, diff and alert correctly against the live site")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline", action="store_true", help="skip Node.js syntax checks and the live simulation")
    args = parser.parse_args()

    report = Report()
    print(f"Validating {WORKFLOW_PATH}")
    try:
        workflow = json.loads(WORKFLOW_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        print(f"  [FAIL] workflow.json is not parseable: {error}")
        return 1
    report.check(True, "workflow.json is valid JSON")

    validate_structure(workflow, report)

    if not args.offline:
        node_bin = shutil.which("node")
        if node_bin is None:
            report.check(False, "Node.js is available for code-node checks (use --offline to skip)")
        else:
            syntax_check_code_nodes(workflow, report, node_bin)
            run_simulation(report, node_bin)

    print(f"\n{report.passes} passed, {len(report.failures)} failed")
    return 1 if report.failures else 0


if __name__ == "__main__":
    sys.exit(main())
