"""SARIF 2.1.0 output for `authzlock diff --format sarif`, for GitHub code scanning.

The log is built from the JSON document of `render.to_document`: one run, driver
`authzlock` with one rule per label, and one result per route change. Custom permission
registry changes have no route and are not results. `partialFingerprints` carries the route
key so code scanning keeps one alert per route across pushes.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from authzlock.render import SUMMARY_LABELS, format_value, render_json

SARIF_VERSION = "2.1.0"
SARIF_SCHEMA = "https://json.schemastore.org/sarif-2.1.0.json"
INFORMATION_URI = "https://github.com/smhasan94/authzlock"
FINGERPRINT = "authzlock/routeKey"

LEVELS: Mapping[str, str] = {
    "loosened": "error",
    "changed-unknown": "warning",
    "added": "warning",
    "tightened": "note",
    "removed": "note",
    "equivalent": "note",
}
_DESCRIPTIONS: Mapping[str, str] = {
    "loosened": "A route's access rules became less restrictive.",
    "tightened": "A route's access rules became more restrictive.",
    "added": "A route was added; review who may call it.",
    "removed": "A route was removed.",
    "changed-unknown": "A route's access rules changed in a way authzlock cannot rank.",
    "equivalent": "A route's permission list changed but no method's effective rule did.",
}


def _rule(label: str) -> dict[str, Any]:
    return {
        "id": label,
        "name": label.title().replace("-", ""),
        "shortDescription": {"text": _DESCRIPTIONS[label]},
        "defaultConfiguration": {"level": LEVELS[label]},
        "helpUri": f"{INFORMATION_URI}/blob/main/docs/classification.md",
    }


def _message(change: Mapping[str, Any]) -> str:
    details = "; ".join(
        f"{field['field']}: {format_value(field['old'])} -> {format_value(field['new'])}"
        for field in change["fields"]
    )
    text = f"{change['label']} {change['route']['key']}"
    if details:
        text += f"  {details}"
    return f"{text}  ({change['reason']})"


def _result(change: Mapping[str, Any]) -> dict[str, Any]:
    location = change["location"]
    return {
        "ruleId": change["label"],
        "level": LEVELS[change["label"]],
        "message": {"text": _message(change)},
        "locations": [
            {
                "physicalLocation": {
                    "artifactLocation": {"uri": location["file"], "uriBaseId": "%SRCROOT%"},
                    "region": {"startLine": location["line"]},
                }
            }
        ],
        "partialFingerprints": {FINGERPRINT: change["route"]["key"]},
    }


def to_sarif(document: Mapping[str, Any]) -> dict[str, Any]:
    """The SARIF log for a `render.to_document` document."""
    base = document["base"]
    invocation: dict[str, Any] = {"executionSuccessful": True}
    if not base["lockfile_found"]:
        invocation["toolExecutionNotifications"] = [
            {
                "level": "note",
                "message": {
                    "text": f"base ref has no authz.lock ({base['ref']}:{base['lockfile']}); "
                    "every route is reported as added"
                },
            }
        ]
    return {
        "$schema": SARIF_SCHEMA,
        "version": SARIF_VERSION,
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": document["tool"]["name"],
                        "version": document["tool"]["version"],
                        "informationUri": INFORMATION_URI,
                        "rules": [_rule(label) for label in SUMMARY_LABELS],
                    }
                },
                "invocations": [invocation],
                "results": [_result(change) for change in document["changes"]],
            }
        ],
    }


def render_sarif(document: Mapping[str, Any]) -> str:
    """The SARIF log for `document` as indented JSON with a trailing newline."""
    return render_json(to_sarif(document))
