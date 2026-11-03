#!/usr/bin/env python3
"""Google Search Console Search Analytics client using application-default auth."""
from __future__ import annotations

import datetime as dt
import os
import time
from typing import Any
from urllib.parse import quote


API_ROOT = "https://searchconsole.googleapis.com/webmasters/v3/sites"
SCOPES = ["https://www.googleapis.com/auth/webmasters.readonly"]


class SearchConsoleError(RuntimeError):
    """An explicit Search Console API or authentication failure."""


class SearchConsoleClient:
    def __init__(self, session: Any) -> None:
        self.session = session

    @classmethod
    def from_application_default_credentials(cls) -> "SearchConsoleClient":
        if os.environ.get("GCP_USE_ADC") != "true":
            raise SearchConsoleError("GCP_USE_ADC is not enabled for this run")
        try:
            import google.auth
            from google.auth.transport.requests import AuthorizedSession
        except ImportError as exc:
            raise SearchConsoleError(
                "google-auth is required for Search Console authentication"
            ) from exc
        try:
            credentials, _ = google.auth.default(scopes=SCOPES)
        except (google.auth.exceptions.GoogleAuthError, OSError) as exc:
            raise SearchConsoleError(
                f"Application default credentials are unavailable: {exc}"
            ) from exc
        return cls(AuthorizedSession(credentials))

    def _query(self, property_id: str, start: dt.date, end: dt.date,
               dimensions: list[str] | None = None) -> list[dict[str, Any]]:
        url = f"{API_ROOT}/{quote(property_id, safe='')}/searchAnalytics/query"
        payload: dict[str, Any] = {
            "startDate": start.isoformat(),
            "endDate": end.isoformat(),
            "rowLimit": 25000,
            "dataState": "final",
            "type": "web",
        }
        if dimensions:
            payload["dimensions"] = dimensions
        rows = []
        offset = 0
        while True:
            request_payload = {**payload, "startRow": offset}
            response = None
            for attempt in range(3):
                try:
                    response = self.session.post(url, json=request_payload, timeout=30)
                except Exception as exc:
                    if attempt < 2:
                        time.sleep(2 ** attempt)
                        continue
                    raise SearchConsoleError(
                        f"Search Console request failed ({type(exc).__name__}): {exc}"
                    ) from exc
                if response.status_code in (408, 429, 500, 502, 503, 504) and attempt < 2:
                    time.sleep(2 ** attempt)
                    continue
                break
            if response is None:
                raise SearchConsoleError("Search Console API retry limit exceeded")
            if response.status_code == 403:
                raise SearchConsoleError(
                    "Search Console permission denied (HTTP 403); verify service-account "
                    "property access and API enablement"
                )
            if response.status_code == 404:
                raise SearchConsoleError(
                    "Search Console property was not found or is not accessible (HTTP 404)"
                )
            if response.status_code >= 400:
                raise SearchConsoleError(
                    f"Search Console API returned HTTP {response.status_code}: "
                    f"{response.text[:300]}"
                )
            try:
                body = response.json()
            except ValueError as exc:
                raise SearchConsoleError("Search Console API returned invalid JSON") from exc
            batch = body.get("rows", [])
            if not isinstance(batch, list):
                raise SearchConsoleError("Search Console API response has invalid rows")
            rows.extend(batch)
            if len(batch) < payload["rowLimit"]:
                return rows
            offset += len(batch)

    @staticmethod
    def _metrics(rows: list[dict[str, Any]]) -> dict[str, float | int]:
        if not rows:
            return {"clicks": 0, "impressions": 0, "ctr": 0.0, "position": 0.0}
        clicks = sum(float(row.get("clicks", 0)) for row in rows)
        impressions = sum(float(row.get("impressions", 0)) for row in rows)
        weighted_position = sum(
            float(row.get("position", 0)) * float(row.get("impressions", 0))
            for row in rows
        )
        return {
            "clicks": int(clicks),
            "impressions": int(impressions),
            "ctr": clicks / impressions if impressions else 0.0,
            "position": weighted_position / impressions if impressions else 0.0,
        }

    @classmethod
    def _aggregate_dimension(cls, rows: list[dict[str, Any]],
                             dimension: str, key_index: int) -> list[dict[str, Any]]:
        buckets: dict[str, list[float]] = {}
        for row in rows:
            keys = row.get("keys", [])
            if len(keys) <= key_index:
                continue
            bucket = buckets.setdefault(str(keys[key_index]), [0.0, 0.0, 0.0])
            clicks = float(row.get("clicks", 0))
            impressions = float(row.get("impressions", 0))
            bucket[0] += clicks
            bucket[1] += impressions
            bucket[2] += float(row.get("position", 0)) * impressions
        return [
            {
                dimension: key,
                "clicks": int(values[0]),
                "impressions": int(values[1]),
                "ctr": values[0] / values[1] if values[1] else 0.0,
                "position": values[2] / values[1] if values[1] else 0.0,
            }
            for key, values in buckets.items()
        ]

    def collect(self, property_id: str, today: dt.date | None = None) -> dict[str, Any]:
        """Return two adjacent 28-day periods, excluding the latest four days."""
        if not property_id.strip():
            return {"status": "not_configured", "error": None}
        today = today or dt.datetime.now(dt.timezone.utc).date()
        current_end = today - dt.timedelta(days=4)
        current_start = current_end - dt.timedelta(days=27)
        previous_end = current_start - dt.timedelta(days=1)
        previous_start = previous_end - dt.timedelta(days=27)

        periods: dict[str, dict[str, Any]] = {}
        for label, start, end in (
            ("current", current_start, current_end),
            ("previous", previous_start, previous_end),
        ):
            total_rows = self._query(property_id, start, end)
            periods[label] = {
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
                "metrics": self._metrics(total_rows),
            }
        current_query_pages = self._query(
            property_id, current_start, current_end, ["query", "page"])
        previous_query_pages = self._query(
            property_id, previous_start, previous_end, ["query", "page"])
        countries = self._query(property_id, current_start, current_end, ["country"])
        devices = self._query(property_id, current_start, current_end, ["device"])

        current_total = periods["current"]["metrics"]
        return {
            "status": "ok" if current_total["impressions"] else "insufficient_data",
            "error": None,
            "periods": periods,
            "queries": {
                "current": self._aggregate_dimension(current_query_pages, "query", 0),
                "previous": self._aggregate_dimension(previous_query_pages, "query", 0),
            },
            "pages": {
                "current": self._aggregate_dimension(current_query_pages, "page", 1),
                "previous": self._aggregate_dimension(previous_query_pages, "page", 1),
            },
            "query_pages": {
                label: [
                    {"query": row["keys"][0], "page": row["keys"][1],
                     **self._metrics([row])}
                    for row in rows if len(row.get("keys", [])) == 2
                ]
                for label, rows in (("current", current_query_pages),
                                    ("previous", previous_query_pages))
            },
            "countries": self._aggregate_dimension(countries, "country", 0),
            "devices": self._aggregate_dimension(devices, "device", 0),
        }


def build_client() -> SearchConsoleClient:
    return SearchConsoleClient.from_application_default_credentials()
