"""Build the n8n laptop price monitor workflow (B-n8n/workflow.json).

Code-node JavaScript lives in B-n8n/code/*.js so it can be reviewed, linted and
tested in isolation; this script embeds it into an importable n8n v1 workflow.
Node IDs are derived with uuid5 so rebuilding produces a stable diff.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
CODE_DIR = ROOT / "code"
OUTPUT_PATH = ROOT / "workflow.json"

WORKFLOW_NAME = "Laptop Price Monitor - Paginated Scrape, Diff & Alert"
NAMESPACE = uuid.UUID("5f0c8a52-6a7e-4c1e-9d8a-0b1c2d3e4f50")
TARGET_URL = "https://webscraper.io/test-sites/e-commerce/static/computers/laptops"
USER_AGENT = "Mozilla/5.0 (compatible; NuredermPriceMonitor/1.0; +https://webscraper.io/test-sites)"

TELEGRAM_CHAT_ID = "REPLACE_WITH_TELEGRAM_CHAT_ID"
GOOGLE_SHEET_ID = "REPLACE_WITH_GOOGLE_SHEET_ID"
HISTORY_SHEET_NAME = "price_history"

HISTORY_COLUMNS: list[tuple[str, str]] = [
    ("run_id", "string"),
    ("scraped_at", "string"),
    ("product_id", "string"),
    ("title", "string"),
    ("price", "number"),
    ("currency", "string"),
    ("review_count", "number"),
    ("rating", "number"),
    ("url", "string"),
    ("page", "number"),
    ("change_type", "string"),
    ("previous_price", "number"),
    ("price_delta", "number"),
    ("price_delta_pct", "number"),
    ("is_anomaly", "boolean"),
    ("is_baseline_run", "boolean"),
]


def stable_id(key: str) -> str:
    return str(uuid.uuid5(NAMESPACE, key))


def load_js(filename: str) -> str:
    return (CODE_DIR / filename).read_text(encoding="utf-8").strip() + "\n"


def node(
    name: str,
    node_type: str,
    type_version: float,
    position: tuple[int, int],
    parameters: dict[str, Any],
    **extra: Any,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "parameters": parameters,
        "id": stable_id(f"node:{name}"),
        "name": name,
        "type": node_type,
        "typeVersion": type_version,
        "position": list(position),
    }
    result.update(extra)
    return result


def code_node(name: str, position: tuple[int, int], filename: str, **extra: Any) -> dict[str, Any]:
    return node(name, "n8n-nodes-base.code", 2, position, {"jsCode": load_js(filename)}, **extra)


def condition(key: str, left: str, right: Any, op_type: str, operation: str) -> dict[str, Any]:
    operator: dict[str, Any] = {"type": op_type, "operation": operation}
    if operation in {"true", "false"}:
        operator["singleValue"] = True
    return {"id": stable_id(f"cond:{key}"), "leftValue": left, "rightValue": right, "operator": operator}


def condition_block(conditions: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "options": {"caseSensitive": True, "leftValue": "", "typeValidation": "strict", "version": 2},
        "conditions": conditions,
        "combinator": "and",
    }


def if_node(name: str, position: tuple[int, int], conditions: list[dict[str, Any]]) -> dict[str, Any]:
    return node(name, "n8n-nodes-base.if", 2.2, position, {"conditions": condition_block(conditions), "options": {}})


def telegram_node(name: str, position: tuple[int, int], chat_id: str, **extra: Any) -> dict[str, Any]:
    return node(
        name,
        "n8n-nodes-base.telegram",
        1.2,
        position,
        {
            "chatId": chat_id,
            "text": "={{ $json.text }}",
            "additionalFields": {
                "appendAttribution": False,
                "disable_web_page_preview": True,
                "parse_mode": "Markdown",
            },
        },
        **extra,
    )


def sheet_locator() -> dict[str, Any]:
    return {
        "documentId": {
            "__rl": True,
            "value": "={{ $('Workflow Config').first().json.googleSheetId }}",
            "mode": "id",
        },
        "sheetName": {
            "__rl": True,
            "value": "={{ $('Workflow Config').first().json.historySheetName }}",
            "mode": "name",
        },
    }


def sticky(name: str, position: tuple[int, int], width: int, height: int, color: int, content: str) -> dict[str, Any]:
    return node(
        name,
        "n8n-nodes-base.stickyNote",
        1,
        position,
        {"content": content, "height": height, "width": width, "color": color},
    )


def assignment(name: str, value: Any, value_type: str) -> dict[str, Any]:
    return {"id": stable_id(f"assign:{name}"), "name": name, "value": value, "type": value_type}


def build_nodes() -> list[dict[str, Any]]:
    history_schema = [
        {
            "id": column,
            "displayName": column,
            "required": False,
            "defaultMatch": False,
            "display": True,
            "type": column_type,
            "canBeUsedToMatch": True,
        }
        for column, column_type in HISTORY_COLUMNS
    ]

    return [
        # Main pipeline: trigger and configuration
        node(
            "Daily 09:00 Trigger",
            "n8n-nodes-base.scheduleTrigger",
            1.2,
            (0, 300),
            {"rule": {"interval": [{"field": "cronExpression", "expression": "0 9 * * *"}]}},
        ),
        node(
            "Workflow Config",
            "n8n-nodes-base.set",
            3.4,
            (220, 300),
            {
                "mode": "manual",
                "assignments": {
                    "assignments": [
                        assignment("maxPages", 50, "number"),
                        assignment("requestDelaySeconds", 1, "number"),
                        assignment("priceAnomalyThresholdPct", 20, "number"),
                        assignment("telegramChatId", TELEGRAM_CHAT_ID, "string"),
                        assignment("googleSheetId", GOOGLE_SHEET_ID, "string"),
                        assignment("historySheetName", HISTORY_SHEET_NAME, "string"),
                    ]
                },
                "options": {},
            },
        ),
        code_node("Init Pagination State", (440, 300), "init_pagination_state.js"),
        # Pagination loop
        node("Pagination State", "n8n-nodes-base.noOp", 1, (660, 300), {}),
        node(
            "Fetch Laptop Page",
            "n8n-nodes-base.httpRequest",
            4.2,
            (880, 300),
            {
                "url": f"={TARGET_URL}?page={{{{ $json.page }}}}",
                "sendHeaders": True,
                "headerParameters": {
                    "parameters": [
                        {"name": "User-Agent", "value": USER_AGENT},
                        {"name": "Accept", "value": "text/html,application/xhtml+xml"},
                    ]
                },
                "options": {
                    "response": {
                        "response": {
                            "fullResponse": True,
                            "neverError": True,
                            "responseFormat": "text",
                            "outputPropertyName": "data",
                        }
                    },
                    "timeout": 30000,
                },
            },
            retryOnFail=True,
            maxTries=3,
            waitBetweenTries=3000,
            onError="continueErrorOutput",
        ),
        if_node(
            "HTTP Status OK?",
            (1100, 200),
            [
                condition("http-gte-200", "={{ $json.statusCode }}", 200, "number", "gte"),
                condition("http-lt-300", "={{ $json.statusCode }}", 300, "number", "lt"),
            ],
        ),
        code_node("Parse & Normalize Page", (1320, 200), "parse_normalize_page.js"),
        if_node(
            "Page Healthy?",
            (1540, 200),
            [condition("page-status-ok", "={{ $json.status }}", "ok", "string", "equals")],
        ),
        if_node(
            "Has Next Page?",
            (1760, 100),
            [
                condition("has-next", "={{ $json.hasNextPage }}", "", "boolean", "true"),
                condition("below-max-pages", "={{ $json.page }}", "={{ $json.maxPages }}", "number", "lt"),
            ],
        ),
        code_node("Advance Page", (1980, -20), "advance_page.js"),
        node(
            "Polite Delay",
            "n8n-nodes-base.wait",
            1.1,
            (2200, -20),
            {"amount": "={{ $('Workflow Config').first().json.requestDelaySeconds }}", "unit": "seconds"},
            webhookId=stable_id("webhook:Polite Delay"),
        ),
        # Persistence and diff
        code_node("Finalize Snapshot", (1980, 220), "finalize_snapshot.js"),
        node(
            "Read Price History",
            "n8n-nodes-base.googleSheets",
            4.5,
            (2200, 220),
            {"operation": "read", **sheet_locator(), "options": {}},
            executeOnce=True,
            alwaysOutputData=True,
        ),
        code_node("Detect Price Changes", (2420, 220), "detect_price_changes.js"),
        node(
            "Append Snapshot to History",
            "n8n-nodes-base.googleSheets",
            4.5,
            (2660, 100),
            {
                "operation": "append",
                **sheet_locator(),
                "columns": {
                    "mappingMode": "autoMapInputData",
                    "value": {},
                    "matchingColumns": [],
                    "schema": history_schema,
                },
                "options": {},
            },
        ),
        node(
            "Only Changed or New",
            "n8n-nodes-base.filter",
            2.2,
            (2660, 340),
            {
                "conditions": condition_block(
                    [
                        condition("changed", "={{ $json.change_type }}", "UNCHANGED", "string", "notEquals"),
                        condition("not-baseline", "={{ $json.is_baseline_run }}", "", "boolean", "false"),
                    ]
                ),
                "options": {},
            },
        ),
        code_node("Build Alert Message", (2880, 340), "build_alert_message.js"),
        telegram_node(
            "Send Price Change Alert",
            (3100, 340),
            "={{ $('Workflow Config').first().json.telegramChatId }}",
        ),
        # Controlled failure branch
        code_node("Build Failure Payload", (1320, 560), "build_failure_payload.js"),
        telegram_node(
            "Send Failure Alert",
            (1540, 560),
            "={{ $('Workflow Config').first().json.telegramChatId }}",
            onError="continueRegularOutput",
        ),
        node(
            "Abort Execution",
            "n8n-nodes-base.stopAndError",
            1,
            (1760, 560),
            {"errorMessage": "={{ $('Build Failure Payload').first().json.summary }}"},
        ),
        # Global safety net (requires Settings > Error Workflow = this workflow)
        node("On Unhandled Workflow Error", "n8n-nodes-base.errorTrigger", 1, (0, 860), {}),
        code_node("Format Unhandled Error", (220, 860), "format_unhandled_error.js"),
        telegram_node("Send Critical Alert", (440, 860), TELEGRAM_CHAT_ID),
        # Documentation
        sticky(
            "Note: Overview",
            (-40, -160),
            620,
            400,
            7,
            "## Laptop Price Monitor\n"
            "Baseline template: **Competitor price monitoring with web scraping, Google Sheets & Telegram** "
            "(n8n.io/workflows/4640).\n\n"
            "Daily 09:00 (Europe/Istanbul) scrape of every `?page=N` of the webscraper.io laptop catalogue, "
            "USD price strings sanitised to floats, snapshot appended to Google Sheets with an ISO timestamp, "
            "diff against the latest stored price per product and a Telegram Markdown alert for changes.\n\n"
            "**Setup:** edit *Workflow Config* (chat ID, sheet ID), attach Google Sheets + Telegram credentials, "
            "create sheet `price_history` with the header row listed in akis-aciklama.md, then set "
            "*Settings > Error Workflow* to this workflow.",
        ),
        sticky(
            "Note: Pagination Loop",
            (640, -160),
            1780,
            120,
            5,
            "### Pagination loop\n"
            "State (page, accumulated products) flows Pagination State -> Fetch -> Parse -> Has Next Page? -> "
            "Advance Page -> Polite Delay -> back to Pagination State. Exit when the page has no `rel=\"next\"` link "
            "or the `maxPages` safety bound is hit.",
        ),
        sticky(
            "Note: Failure Branch",
            (1280, 720),
            720,
            140,
            3,
            "### Controlled failure branch\n"
            "Transport errors (after 3 retries), non-2xx status codes, zero products on a page or unparsable "
            "price cards all land here: alert is sent, then *Abort Execution* fails the run so nothing is persisted.",
        ),
        sticky(
            "Note: Error Trigger",
            (-40, 1020),
            620,
            120,
            3,
            "### Global safety net\n"
            "Catches anything outside the controlled branch (Sheets/Telegram outages, code exceptions). "
            "Skips errors raised by *Abort Execution* to avoid duplicate alerts.",
        ),
    ]


def link(target: str, index: int = 0) -> dict[str, Any]:
    return {"node": target, "type": "main", "index": index}


def build_connections() -> dict[str, Any]:
    return {
        "Daily 09:00 Trigger": {"main": [[link("Workflow Config")]]},
        "Workflow Config": {"main": [[link("Init Pagination State")]]},
        "Init Pagination State": {"main": [[link("Pagination State")]]},
        "Pagination State": {"main": [[link("Fetch Laptop Page")]]},
        "Fetch Laptop Page": {"main": [[link("HTTP Status OK?")], [link("Build Failure Payload")]]},
        "HTTP Status OK?": {"main": [[link("Parse & Normalize Page")], [link("Build Failure Payload")]]},
        "Parse & Normalize Page": {"main": [[link("Page Healthy?")]]},
        "Page Healthy?": {"main": [[link("Has Next Page?")], [link("Build Failure Payload")]]},
        "Has Next Page?": {"main": [[link("Advance Page")], [link("Finalize Snapshot")]]},
        "Advance Page": {"main": [[link("Polite Delay")]]},
        "Polite Delay": {"main": [[link("Pagination State")]]},
        "Finalize Snapshot": {"main": [[link("Read Price History")]]},
        "Read Price History": {"main": [[link("Detect Price Changes")]]},
        "Detect Price Changes": {"main": [[link("Append Snapshot to History"), link("Only Changed or New")]]},
        "Only Changed or New": {"main": [[link("Build Alert Message")]]},
        "Build Alert Message": {"main": [[link("Send Price Change Alert")]]},
        "Build Failure Payload": {"main": [[link("Send Failure Alert")]]},
        "Send Failure Alert": {"main": [[link("Abort Execution")]]},
        "On Unhandled Workflow Error": {"main": [[link("Format Unhandled Error")]]},
        "Format Unhandled Error": {"main": [[link("Send Critical Alert")]]},
    }


def build_workflow() -> dict[str, Any]:
    return {
        "name": WORKFLOW_NAME,
        "nodes": build_nodes(),
        "connections": build_connections(),
        "active": False,
        "settings": {
            "executionOrder": "v1",
            "timezone": "Europe/Istanbul",
            "saveDataErrorExecution": "all",
            "saveDataSuccessExecution": "all",
            "saveManualExecutions": True,
            "callerPolicy": "workflowsFromSameOwner",
        },
        "pinData": {},
        "versionId": stable_id("version:1"),
        "meta": {"templateCredsSetupCompleted": False},
        "tags": [],
    }


def main() -> None:
    workflow = build_workflow()
    OUTPUT_PATH.write_text(json.dumps(workflow, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {OUTPUT_PATH} ({len(workflow['nodes'])} nodes)")


if __name__ == "__main__":
    main()
