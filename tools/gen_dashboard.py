"""Generates platform/observability/dashboard-sentinel.yaml (a Grafana dashboard ConfigMap).

Edit this script, not the YAML: python3 tools/gen_dashboard.py
"""
import json
from pathlib import Path

NS = 'namespace="$namespace"'
ORD = f'{NS}, handler="/orders", method="POST"'
P, L = {"type": "prometheus", "uid": "prometheus"}, {"type": "loki", "uid": "loki"}


def ts(title, targets, x, y, w=12, h=8, unit="short", desc="", thresholds=None):
    panel = {
        "type": "timeseries", "title": title, "description": desc, "datasource": P,
        "gridPos": {"x": x, "y": y, "w": w, "h": h},
        "fieldConfig": {"defaults": {"unit": unit, "custom": {"lineWidth": 2, "fillOpacity": 8}}, "overrides": []},
        "options": {"legend": {"displayMode": "list", "placement": "bottom"}, "tooltip": {"mode": "multi"}},
        "targets": [{"refId": chr(65 + i), "expr": e, "legendFormat": lg} for i, (e, lg) in enumerate(targets)],
    }
    if thresholds:
        panel["fieldConfig"]["defaults"]["thresholds"] = {"mode": "absolute", "steps": thresholds}
        panel["fieldConfig"]["defaults"]["custom"]["thresholdsStyle"] = {"mode": "line+area"}
    return panel


def stat(title, expr, x, unit, steps, desc=""):
    return {
        "type": "stat", "title": title, "description": desc, "datasource": P,
        "gridPos": {"x": x, "y": 0, "w": 6, "h": 4},
        "fieldConfig": {"defaults": {"unit": unit, "decimals": 2,
                                     "thresholds": {"mode": "absolute", "steps": steps}}, "overrides": []},
        "options": {"colorMode": "background", "reduceOptions": {"calcs": ["lastNotNull"]}},
        "targets": [{"refId": "A", "expr": expr}],
    }


green, amber, red = "green", "#EAB839", "red"
panels = [
    stat("Orders per second", f'sum(rate(http_requests_total{{{ORD}}}[5m]))', 0, "reqps",
         [{"color": "blue", "value": None}]),
    stat("Error rate (5m)", "sentinel:order_api_errors:ratio_rate5m{namespace=\"$namespace\"}", 6, "percentunit",
         [{"color": green, "value": None}, {"color": amber, "value": 0.005}, {"color": red, "value": 0.05}],
         "Share of POST /orders answered with 5xx. SLO: at most 0.5%."),
    stat("p95 latency (5m)", f'histogram_quantile(0.95, sum by (le) (rate(http_request_duration_seconds_bucket{{{ORD}}}[5m])))',
         12, "s", [{"color": green, "value": None}, {"color": amber, "value": 0.25}, {"color": red, "value": 0.5}]),
    stat("Availability burn rate (1h)", "sentinel:order_api_errors:ratio_rate1h{namespace=\"$namespace\"} / 0.005", 18, "x",
         [{"color": green, "value": None}, {"color": amber, "value": 6}, {"color": red, "value": 14.4}],
         "How fast the error budget is being spent. 1x = exactly on budget; 14.4x pages."),
    ts("order-api requests by status", [(f'sum by (status) (rate(http_requests_total{{{ORD}}}[1m]))', "{{status}}")],
       0, 4, unit="reqps"),
    ts("order-api latency", [
        (f'histogram_quantile(0.50, sum by (le) (rate(http_request_duration_seconds_bucket{{{ORD}}}[1m])))', "p50"),
        (f'histogram_quantile(0.95, sum by (le) (rate(http_request_duration_seconds_bucket{{{ORD}}}[1m])))', "p95"),
        (f'histogram_quantile(0.99, sum by (le) (rate(http_request_duration_seconds_bucket{{{ORD}}}[1m])))', "p99"),
    ], 12, 4, unit="s", thresholds=[{"color": "transparent", "value": None}, {"color": red, "value": 0.25}]),
    ts("Canary vs stable error rate", [(
        f'sum by (role) (rate(http_requests_total{{{ORD}, status="5xx"}}[1m])) / sum by (role) (rate(http_requests_total{{{ORD}}}[1m]))',
        "{{role}}")], 0, 12, unit="percentunit",
        desc="During a rollout, canary and stable pods are labelled separately. This is what the canary analysis judges."),
    ts("Error budget burn rate", [
        ("sentinel:order_api_errors:ratio_rate5m{namespace=\"$namespace\"} / 0.005", "5m"),
        ("sentinel:order_api_errors:ratio_rate1h{namespace=\"$namespace\"} / 0.005", "1h"),
        ("sentinel:order_api_errors:ratio_rate6h{namespace=\"$namespace\"} / 0.005", "6h"),
    ], 12, 12, unit="x", thresholds=[{"color": "transparent", "value": None}, {"color": amber, "value": 6},
                                      {"color": red, "value": 14.4}],
       desc="Fast page when 1h AND 5m are above 14.4x; slow alert when 6h AND 30m are above 6x."),
    ts("risk-engine checks and latency", [
        (f'sum(rate(http_requests_total{{{NS}, handler="/v1/check"}}[1m]))', "checks/s"),
        (f'histogram_quantile(0.95, sum by (le) (rate(http_request_duration_seconds_bucket{{{NS}, handler="/v1/check"}}[1m])))', "p95 (s)"),
    ], 0, 20),
    ts("notifier events", [(f'sum by (status) (rate(notifier_events_processed_total{{{NS}}}[1m]))', "{{status}}")],
       12, 20, unit="ops"),
    {
        "type": "logs", "title": "order-api warnings and errors (click a trace_id to open the trace)", "datasource": L,
        "gridPos": {"x": 0, "y": 28, "w": 24, "h": 10},
        "options": {"showTime": True, "wrapLogMessage": True, "sortOrder": "Descending"},
        "targets": [{"refId": "A", "expr": '{namespace="$namespace", app="order-api"} | json | level=~"warning|error"'}],
    },
]
dashboard = {
    "uid": "sentinel-overview", "title": "Sentinel / Overview", "tags": ["sentinel"], "timezone": "browser",
    "schemaVersion": 39, "refresh": "30s", "time": {"from": "now-1h", "to": "now"},
    "templating": {"list": [{
        "name": "namespace", "label": "Environment", "type": "custom", "query": "sentinel-staging,sentinel-prod",
        "current": {"text": "sentinel-staging", "value": "sentinel-staging"},
        "options": [{"text": v, "value": v, "selected": v == "sentinel-staging"} for v in ["sentinel-staging", "sentinel-prod"]],
    }]},
    "panels": [dict(p, id=i + 1) for i, p in enumerate(panels)],
}
body = json.dumps(dashboard, indent=2)
out = Path(__file__).resolve().parent.parent / "platform/observability/dashboard-sentinel.yaml"
out.write_text(
    "# GENERATED by tools/gen_dashboard.py. Do not edit by hand.\n"
    "# Grafana's sidecar loads every ConfigMap labelled grafana_dashboard=1.\n"
    "apiVersion: v1\nkind: ConfigMap\nmetadata:\n  name: grafana-dashboard-sentinel\n  namespace: monitoring\n"
    "  labels:\n    grafana_dashboard: \"1\"\ndata:\n  sentinel-overview.json: |\n"
    + "\n".join("    " + line for line in body.splitlines()) + "\n"
)
print(f"wrote {out.relative_to(out.parents[2])}: {len(panels)} panels")
