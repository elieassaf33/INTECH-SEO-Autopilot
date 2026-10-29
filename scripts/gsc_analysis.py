"""Read-only, paginated weekly Search Console analysis."""
import datetime as dt
from urllib.parse import quote
from zoneinfo import ZoneInfo
from gsc_api import request, error_status

PAGE_SIZE = 25000
MAX_ROWS = 100000


def periods(today=None):
    today = today or dt.datetime.now(ZoneInfo("America/Los_Angeles")).date()
    end = today - dt.timedelta(days=3)
    start = end - dt.timedelta(days=6)
    return (start, end), (start - dt.timedelta(days=7), end - dt.timedelta(days=7))


def fetch_rows(session, prop, period):
    url = "https://searchconsole.googleapis.com/webmasters/v3/sites/" + quote(prop, safe="") + "/searchAnalytics/query"
    rows = []
    while len(rows) < MAX_ROWS:
        payload = request(session, "post", url, json={
            "startDate": period[0].isoformat(), "endDate": period[1].isoformat(),
            "dimensions": ["query", "page"], "type": "web", "dataState": "final",
            "rowLimit": min(PAGE_SIZE, MAX_ROWS - len(rows)), "startRow": len(rows),
        })
        batch = payload.get("rows", [])
        rows.extend(batch)
        if len(batch) < PAGE_SIZE:
            return rows, False
    return rows, True


def site_metrics(session, prop, period):
    """Property aggregates must be requested independently of query/page rows."""
    url = "https://searchconsole.googleapis.com/webmasters/v3/sites/" + quote(prop, safe="") + "/searchAnalytics/query"
    payload = request(session, "post", url, json={
        "startDate": period[0].isoformat(), "endDate": period[1].isoformat(),
        "dimensions": [], "aggregationType": "byProperty", "type": "web", "dataState": "final",
    })
    rows = payload.get("rows", [])
    if not rows:
        return {"status": "no_data", "metrics": None}
    return {"status": "ok", "metrics": {k: rows[0].get(k) for k in ("clicks", "impressions", "ctr", "position")}}


def analyze(current, previous):
    before = {tuple(r["keys"]): r for r in previous}
    after = {tuple(r["keys"]): r for r in current}
    keywords, recommendations = [], []
    for key in sorted(before.keys() | after.keys()):
        now, old = after.get(key, {}), before.get(key, {})
        clicks, impressions = now.get("clicks", 0), now.get("impressions", 0)
        old_clicks = old.get("clicks", 0)
        item = {"keyword": key[0], "page": key[1], "clicks": clicks,
                "impressions": impressions, "ctr": now.get("ctr", 0),
                "position": now.get("position") if impressions else None,
                "previous_clicks": old_clicks,
                "click_change": clicks - old_clicks,
                "click_change_percent": (clicks - old_clicks) / old_clicks * 100 if old_clicks else None,
                "impression_change": impressions - old.get("impressions", 0),
                "position_improvement": old["position"] - now["position"] if old.get("impressions") and impressions else None,
                "presence": "continuing" if key in before and key in after else "newly_observed" if key in after else "no_longer_observed"}
        keywords.append(item)
        actions = []
        if old_clicks >= 5 and clicks <= old_clicks * .7:
            actions.append(("high", "traffic_decline", "Investigate lost clicks: compare indexing, search intent, competitors and recent page changes."))
        if impressions >= 50 and 1 <= now.get("position", 0) <= 10 and now.get("ctr", 0) < .02:
            actions.append(("medium", "low_ctr", "Review the page title and search snippet against this query's intent; propose a clearer title and description."))
        if impressions >= 10 and 5 <= now.get("position", 0) <= 20:
            actions.append(("medium", "ranking_opportunity", "Review query coverage on the landing page and propose relevant content improvements and internal links."))
        for priority, reason, action in actions:
            recommendations.append({**item, "priority": priority, "reason": reason, "action": action})
    recommendations.sort(key=lambda r: (r["priority"] != "high", -r["impressions"], r["keyword"], r["page"], r["reason"]))
    return keywords, recommendations


def weekly_analysis(session, prop, today=None):
    current_period, previous_period = periods(today)
    result = {
            "period": [d.isoformat() for d in current_period],
            "previous_period": [d.isoformat() for d in previous_period],
            "queries": [], "recommendations": [], "row_cap_reached": False,
            "coverage_note": "Query/page rows are partial Search Console data, not site totals. Missing rows do not prove zero traffic. Recommendations are heuristics requiring human review."}
    totals = {}
    for label, period in (("current", current_period), ("previous", previous_period)):
        try:
            totals[label] = site_metrics(session, prop, period)
        except Exception as exc:
            totals[label] = error_status(exc)
    result["site_metrics"] = totals
    if all(totals[k]["status"] == "ok" for k in totals):
        now, old = (totals[k]["metrics"] for k in ("current", "previous"))
        result["site_metric_changes"] = {
            "clicks": now["clicks"] - old["clicks"],
            "impressions": now["impressions"] - old["impressions"],
            "ctr_percentage_points": (now["ctr"] - old["ctr"]) * 100,
            "position_improvement": old["position"] - now["position"],
        }
    try:
        current, current_capped = fetch_rows(session, prop, current_period)
        previous, previous_capped = fetch_rows(session, prop, previous_period)
        result["queries"], result["recommendations"] = analyze(current, previous)
        result["query_status"] = "ok" if current or previous else "no_data"
        result["row_cap_reached"] = current_capped or previous_capped
    except Exception as exc:
        result["query_status"] = "error"
        result["query_error"] = error_status(exc)
    statuses = [t["status"] for t in totals.values()] + [result["query_status"]]
    result["status"] = ("error" if all(s == "error" for s in statuses) else
                        "partial" if "error" in statuses else
                        "no_data" if all(s == "no_data" for s in statuses) else "ok")
    return result
