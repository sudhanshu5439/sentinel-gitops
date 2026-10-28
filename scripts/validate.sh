#!/usr/bin/env bash
# Validates everything in this repo the way the cluster would see it:
#   1. every overlay renders and matches the Kubernetes schemas
#   2. the real overlays PASS the Kyverno policies
#   3. the known-bad fixtures FAIL them (so a broken policy can't silently allow everything)
#   4. the observability content builds, the dashboard JSON parses, and the SLO alert rules pass
#      their unit tests (promtool)
# Needs: kustomize, kubeconform, kyverno (CLI), promtool, python3 with PyYAML.
set -euo pipefail
cd "$(dirname "$0")/.."
POLICIES="platform/policies/restrict-registries.yaml platform/policies/require-resources-and-probes.yaml"
VALUES=tests/policies/values.yaml
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT

for env in staging prod; do
  echo "==> render + schema check: $env"
  kustomize build "apps/overlays/$env" > "$tmp/$env.yaml"
  # Built-in kinds from the Kubernetes schemas; Rollout, AnalysisTemplate and PodMonitor from the
  # community CRD catalog.
  kubeconform -strict -summary -schema-location default \
    -schema-location 'https://raw.githubusercontent.com/datreeio/CRDs-catalog/main/{{.Group}}/{{.ResourceKind}}_{{.ResourceAPIVersion}}.json' \
    "$tmp/$env.yaml"
  echo "==> policies must pass: $env"
  sed "s/sentinel-prod/sentinel-$env/" "$VALUES" > "$tmp/values-$env.yaml"
  # shellcheck disable=SC2086
  kyverno apply $POLICIES --resource "$tmp/$env.yaml" --values-file "$tmp/values-$env.yaml"
done

kubeconform -summary -ignore-missing-schemas argocd/*.yaml bootstrap/*.yaml
kustomize build platform/policies >/dev/null
echo "==> render + schema check: ingress routes"
kustomize build platform/ingress | kubeconform -strict -summary

for bad in tests/policies/bad-*.yaml; do
  echo "==> policies must deny: $bad"
  # shellcheck disable=SC2086
  if kyverno apply $POLICIES --resource "$bad" --values-file "$VALUES" >/dev/null 2>&1; then
    echo "FAIL: $bad was allowed"; exit 1
  fi
  echo "denied as expected"
done
echo "==> observability: render, dashboard JSON, SLO rules + alert unit tests"
kustomize build platform/observability > "$tmp/obs.yaml"
python3 - "$tmp" <<'PY'
import json, sys, yaml
tmp = sys.argv[1]
docs = [d for d in yaml.safe_load_all(open(f"{tmp}/obs.yaml")) if d]
for d in docs:
    if d["kind"] == "ConfigMap" and d["metadata"].get("labels", {}).get("grafana_dashboard") == "1":
        for name, body in d["data"].items():
            json.loads(body)
            print(f"dashboard ok: {name}")
    if d["kind"] == "PrometheusRule":
        yaml.safe_dump(d["spec"], open(f"{tmp}/rules.yaml", "w"))
PY
promtool check rules "$tmp/rules.yaml"
cp tests/slo/*.test.yaml "$tmp/"
(cd "$tmp" && for t in *.test.yaml; do promtool test rules "$t"; done)

echo "All checks passed."
