#!/usr/bin/env bash
# Renders every Helm-based Argo CD Application in argocd/ with its exact chart version and values,
# then schema-checks the output. Catches bad values (most charts ship a values JSON schema) and
# broken templates BEFORE Argo CD tries to sync them. Needs: helm, kubeconform, python3 + PyYAML.
set -euo pipefail
cd "$(dirname "$0")/.."
out=$(mktemp -d); trap 'rm -rf "$out"' EXIT

python3 - "$out" <<'PY'
import sys, yaml, pathlib
out = pathlib.Path(sys.argv[1])
for f in sorted(pathlib.Path("argocd").glob("*.yaml")):
    app = yaml.safe_load(f.read_text())
    src = app["spec"]["source"]
    if "chart" not in src:
        continue
    name = app["metadata"]["name"]
    (out / f"{name}.values.yaml").write_text(yaml.safe_dump(src.get("helm", {}).get("valuesObject", {})))
    ns = app["spec"]["destination"].get("namespace", "default")
    (out / "apps.txt").open("a").write(f'{name} {src["repoURL"]} {src["chart"]} {src["targetRevision"]} {ns}\n')
PY

status=0
while read -r name repo chart version ns; do
  echo "==> $name: $chart $version from $repo"
  if helm template "$name" "$chart" --repo "$repo" --version "$version" --namespace "$ns" \
       --kube-version 1.33.0 -f "$out/$name.values.yaml" > "$out/$name.yaml" 2> "$out/$name.err"; then
    kinds=$(grep -E '^kind:' "$out/$name.yaml" | sort | uniq -c | awk '{printf "%s %s, ", $1, $3}')
    svcs=$(python3 -c "import sys,yaml; print(' '.join(d['metadata']['name'] for d in yaml.safe_load_all(open(sys.argv[1])) if d and d.get('kind')=='Service'))" "$out/$name.yaml")
    echo "::notice title=$name rendered::$kinds services: $svcs"
    kubeconform -summary -ignore-missing-schemas -kubernetes-version 1.33.0 "$out/$name.yaml" || status=1
  else
    echo "::error title=$name failed to render::$(tr '\n' ' ' < "$out/$name.err" | cut -c1-900)"
    status=1
  fi
done < "$out/apps.txt"
exit $status
