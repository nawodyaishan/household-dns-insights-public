"""Shared bounded, generation-aware extraction envelope validation."""

from __future__ import annotations

from collections.abc import Mapping


class CaptureError(ValueError):
    """A successful capture envelope is invalid or ambiguous."""


def validate_campaign_snapshot(snapshot: Mapping[str, object]) -> None:
    """Validate a successful read, including a distinct zero-row envelope."""
    if int(snapshot.get("schema_version", 0)) != 2 or snapshot.get("read_state") != "ok":
        raise CaptureError("Campaign capture needs an explicit successful read")
    start, end = int(snapshot["start_epoch"]), int(snapshot["end_epoch"])
    if start >= end or end - start > 3600:
        raise CaptureError("Campaign capture exceeds the bounded window")
    rows = snapshot.get("observations")
    if not isinstance(rows, list) or len(rows) != int(snapshot["window_count"]):
        raise CaptureError("Campaign capture count does not match its rows")
    if not isinstance(snapshot.get("source_generation"), str) or not snapshot["source_generation"]:
        raise CaptureError("Campaign capture is missing its configured source generation")
    if not isinstance(snapshot.get("captured_utc"), str) or not snapshot["captured_utc"]:
        raise CaptureError("Campaign capture is missing its capture time")
    ids = [int(row["id"]) for row in rows]
    if len(ids) != len(set(ids)) or any(source_id < 0 for source_id in ids):
        raise CaptureError("Campaign capture contains invalid source query IDs")
    for row in rows:
        if not start <= float(row["timestamp"]) < end or not str(row.get("domain", "")).strip():
            raise CaptureError("Campaign capture contains an invalid row")
