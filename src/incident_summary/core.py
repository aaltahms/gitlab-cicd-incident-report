"""Validate incident data and produce deterministic summaries."""

from __future__ import annotations

import html
import json
import math
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, median
from typing import Any, Dict, Iterable, List

SEVERITIES = ("low", "medium", "high", "critical")
STATUSES = ("open", "investigating", "resolved", "closed")


class IncidentValidationError(ValueError):
    """Raised when an incident fixture does not match the expected schema."""


def _parse_timestamp(value: Any, field: str, incident_id: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise IncidentValidationError(f"{incident_id}: {field} must be a non-empty ISO-8601 string")
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise IncidentValidationError(f"{incident_id}: {field} is not a valid ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise IncidentValidationError(f"{incident_id}: {field} must include a timezone")
    return parsed.astimezone(timezone.utc)


def validate_incidents(raw: Any) -> List[Dict[str, Any]]:
    if not isinstance(raw, list):
        raise IncidentValidationError("input must be a JSON array")

    validated: List[Dict[str, Any]] = []
    seen_ids = set()
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise IncidentValidationError(f"record {index}: incident must be an object")

        incident_id = item.get("id")
        if not isinstance(incident_id, str) or not incident_id.strip():
            raise IncidentValidationError(f"record {index}: id must be a non-empty string")
        incident_id = incident_id.strip()
        unknown = set(item) - {"id", "severity", "status", "service", "opened_at", "resolved_at"}
        if unknown:
            raise IncidentValidationError(f"{incident_id}: unknown fields: {sorted(unknown)}")
        if incident_id in seen_ids:
            raise IncidentValidationError(f"{incident_id}: duplicate id")
        seen_ids.add(incident_id)

        severity = item.get("severity")
        status = item.get("status")
        service = item.get("service")
        if severity not in SEVERITIES:
            raise IncidentValidationError(f"{incident_id}: unsupported severity {severity!r}")
        if status not in STATUSES:
            raise IncidentValidationError(f"{incident_id}: unsupported status {status!r}")
        if not isinstance(service, str) or not service.strip():
            raise IncidentValidationError(f"{incident_id}: service must be a non-empty string")

        opened_at = _parse_timestamp(item.get("opened_at"), "opened_at", incident_id)
        resolved_value = item.get("resolved_at")
        resolved_at = None
        if resolved_value is not None:
            resolved_at = _parse_timestamp(resolved_value, "resolved_at", incident_id)
            if resolved_at < opened_at:
                raise IncidentValidationError(f"{incident_id}: resolved_at precedes opened_at")
        if status in ("resolved", "closed") and resolved_at is None:
            raise IncidentValidationError(f"{incident_id}: {status} incidents require resolved_at")

        if status in ("open", "investigating") and resolved_at is not None:
            raise IncidentValidationError(f"{incident_id}: active incidents cannot have resolved_at")

        validated.append(
            {
                "id": incident_id,
                "severity": severity,
                "status": status,
                "service": service.strip(),
                "opened_at": opened_at,
                "resolved_at": resolved_at,
            }
        )
    return validated


def load_incidents(path: Path) -> List[Dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        return validate_incidents(json.load(handle))


def build_summary(incidents: Iterable[Dict[str, Any]], as_of: datetime = None) -> Dict[str, Any]:
    """Summarize validated rows. Optional snapshot enables reproducible backlog aging."""
    rows = list(incidents)
    if as_of is not None:
        if as_of.tzinfo is None:
            raise IncidentValidationError("as_of must include a timezone")
        as_of = as_of.astimezone(timezone.utc)
        if any(row["opened_at"] > as_of or (row["resolved_at"] is not None and row["resolved_at"] > as_of) for row in rows):
            raise IncidentValidationError("snapshot precedes an incident event; historical state cannot be inferred")
    severity_counts = Counter(row["severity"] for row in rows)
    status_counts = Counter(row["status"] for row in rows)
    service_counts = Counter(row["service"] for row in rows)
    resolution_minutes = [
        (row["resolved_at"] - row["opened_at"]).total_seconds() / 60
        for row in rows
        if row["resolved_at"] is not None
    ]

    active = [row for row in rows if row["status"] in ("open", "investigating")]
    ordered_durations = sorted(resolution_minutes)
    backlog = [] if as_of is None else sorted(
        ({"id": row["id"], "service": row["service"], "severity": row["severity"],
          "age_minutes": round((as_of - row["opened_at"]).total_seconds() / 60, 2)} for row in active),
        key=lambda row: (-row["age_minutes"], row["id"]))
    return {
        "schema_version": 1,
        "as_of": as_of.isoformat() if as_of else None,
        "active_backlog": backlog,
        "resolution_sample_size": len(resolution_minutes),
        "p90_resolution_minutes": round(ordered_durations[math.ceil(.9 * len(ordered_durations)) - 1], 2) if ordered_durations else None,
        "total_incidents": len(rows),
        "active_incidents": sum(status_counts[name] for name in ("open", "investigating")),
        "resolved_incidents": sum(status_counts[name] for name in ("resolved", "closed")),
        "by_severity": {name: severity_counts[name] for name in SEVERITIES},
        "by_status": {name: status_counts[name] for name in STATUSES},
        "by_service": dict(sorted(service_counts.items())),
        "mean_resolution_minutes": round(mean(resolution_minutes), 2) if resolution_minutes else None,
        "median_resolution_minutes": round(median(resolution_minutes), 2) if resolution_minutes else None,
    }


def render_html(summary: Dict[str, Any]) -> str:
    service_rows = "".join(
        f"<tr><td>{html.escape(str(service))}</td><td>{count}</td></tr>"
        for service, count in summary["by_service"].items()
    )
    severity_rows = "".join(
        f"<tr><td>{name.title()}</td><td>{summary['by_severity'][name]}</td></tr>"
        for name in SEVERITIES
    )
    mean_value = summary["mean_resolution_minutes"]
    median_value = summary["median_resolution_minutes"]
    mean_text = "N/A" if mean_value is None else f"{mean_value:.2f} min"
    median_text = "N/A" if median_value is None else f"{median_value:.2f} min"
    backlog_rows = "".join(
        f"<tr><td>{html.escape(row['id'])}</td><td>{html.escape(row['service'])}</td><td>{html.escape(row['severity'])}</td><td>{row['age_minutes']}</td></tr>"
        for row in summary["active_backlog"]
    )
    snapshot = html.escape(summary["as_of"] or "Not supplied; aging unavailable")
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Incident Summary</title>
  <style>
    body {{ font: 16px/1.5 system-ui, sans-serif; margin: 0; background: #f4f6f8; color: #17202a; }}
    main {{ max-width: 900px; margin: 48px auto; padding: 0 20px; }}
    .cards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 16px; }}
    .card, section {{ background: white; border: 1px solid #d9e0e7; border-radius: 10px; padding: 18px; }}
    .card strong {{ display: block; font-size: 1.8rem; }}
    section {{ margin-top: 18px; }}
    table {{ width: 100%; border-collapse: collapse; }}
    th, td {{ text-align: left; padding: 8px; border-bottom: 1px solid #e5e9ed; }}
  </style>
</head>
<body>
<main>
  <h1>Incident Summary</h1>
  <p>Portfolio demonstration · included dataset is synthetic.</p>
  <p>Snapshot: {snapshot}</p>
  <div class="cards">
    <div class="card"><strong>{summary['total_incidents']}</strong>Total incidents</div>
    <div class="card"><strong>{summary['active_incidents']}</strong>Active</div>
    <div class="card"><strong>{summary['resolved_incidents']}</strong>Resolved/closed</div>
    <div class="card"><strong>{mean_text}</strong>Mean resolution</div>
    <div class="card"><strong>{median_text}</strong>Median resolution</div>
  </div>
  <section><h2>Severity</h2><table><thead><tr><th scope="col">Severity</th><th scope="col">Count</th></tr></thead><tbody>{severity_rows}</tbody></table></section>
  <section><h2>Services</h2><table><thead><tr><th scope="col">Service</th><th scope="col">Count</th></tr></thead><tbody>{service_rows}</tbody></table></section>
  <section><h2>Active backlog</h2><table><thead><tr><th scope="col">ID</th><th scope="col">Service</th><th scope="col">Severity</th><th scope="col">Age (minutes)</th></tr></thead><tbody>{backlog_rows}</tbody></table></section>
  <p>Resolution sample: {summary["resolution_sample_size"]}; 90th percentile (nearest rank): {summary["p90_resolution_minutes"]} minutes. These describe this dataset, not measured workplace outcomes.</p>
</main>
</body>
</html>
"""
