"""Simulation bug detection — errors and bug report generation."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path


class SimulationBugError(Exception):
    """Raised when an internal simulation invariant is violated."""
    pass


def _write_bug_report(error_msg: str, context_dict: dict, config) -> None:
    """Write a JSON bug report and raise SimulationBugError.

    Args:
        error_msg: Description of the invariant violation.
        context_dict: Snapshot of relevant state (month, bucket, lots, etc.).
        config: SimConfig instance — serialized via model_dump_json().

    Raises:
        SimulationBugError with the report file path.
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"bug_report_{timestamp}.json"
    report = {
        "error": error_msg,
        "context": context_dict,
        "config": json.loads(config.model_dump_json()),
    }
    path = Path(filename)
    path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    raise SimulationBugError(
        f"Simulation bug detected: {error_msg} — report written to {path.resolve()}"
    )
