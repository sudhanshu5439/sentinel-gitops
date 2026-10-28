# sentinel-gitops

[![validate](https://github.com/sudhanshu5439/sentinel-gitops/actions/workflows/validate.yml/badge.svg)](https://github.com/sudhanshu5439/sentinel-gitops/actions/workflows/validate.yml)

The desired state of the [Sentinel](https://github.com/sudhanshu5439/sentinel) platform. Argo CD
watches this repo and keeps the cluster identical to it: releases, rollbacks and platform
changes are commits and pull requests here. Nobody runs `kubectl apply` by hand (the one
exception is `bootstrap/root.yaml`, applied once).

```
bootstrap/root.yaml          the only object applied manually ("app of apps")
argocd/                      one Argo CD Application per component, ordered by sync waves:
  00-kyverno                   admission controller
  01-policies                  Sentinel's Kyverno policies (platform/policies)
  02-monitoring                Prometheus, Alertmanager, Grafana (kube-prometheus-stack)
  03-argo-rollouts             progressive delivery controller + dashboard
  04-loki · 05-tempo           logs and traces
  06-alloy                     the one telemetry agent: pod logs → Loki, OTLP traces → Tempo
  07-observability-config      SLO rules + alerts, Grafana dashboard (platform/observability)
  08-traefik                   ingress controller for every UI
  09-ingress-routes            hostnames for the UIs (platform/ingress)
  10-sentinel-staging          the apps, staging overlay
  11-sentinel-prod             the apps, prod overlay
platform/                    plain manifests for the apps above
apps/base/                   the Sentinel services, environment-agnostic
apps/overlays/staging/       auto-promoted by CI on every merge to main
apps/overlays/prod/          promoted only through a reviewed pull request
tests/policies/              manifests the policies must reject
tests/slo/                   promtool unit tests for the SLO alerts
scripts/validate.sh          render + schema check + policy tests + SLO tests
scripts/render-helm.sh       renders every Helm-based app with its real values
tools/gen_dashboard.py       generates the Grafana dashboard JSON
```

## How a release reaches production

1. A change merges to `main` in the `sentinel` repo.
2. CI builds, scans, signs and attests the images, then commits their **digests** to
   `apps/overlays/staging`. Argo CD syncs staging within minutes.
3. CI opens a pull request here that updates `apps/overlays/prod` to the same digests (older,
   still-open promotion PRs are closed as superseded).
4. A human reviews and merges it. Argo CD syncs prod.
5. In both namespaces, Kyverno admits a pod only if every Sentinel image is referenced by digest
   and signed by `supply-chain.yml` on `main`, comes from an allowed registry, and declares
   resources and a readiness probe.

In each environment, order-api is an Argo Rollouts **canary**: 25% → 50% → 75% → 100% of pods,
while Prometheus is queried every 30 s about the canary pods only (≥ 10 requests/min, error rate
≤ 5%, p95 latency ≤ 300 ms). A second failed check aborts the rollout and the stable version keeps
serving. A `loadgen` Deployment provides steady traffic so there is always evidence to judge.

Rolling back = reverting a commit in this repo.

## Every change is tested before Argo CD sees it

The `validate` workflow runs on every pull request and push:

- every overlay renders with Kustomize and passes Kubernetes schema validation (kubeconform);
- the real overlays **pass** the Kyverno policies, and known-bad fixtures **must be denied**, so a
  broken policy cannot silently allow everything;
- the SLO alert rules pass their `promtool` unit tests (a bad release pages, a one-minute blip
  doesn't, a healthy service never alerts);
- every Helm-based Application is rendered with its exact chart version and values, and
  schema-checked. This caught a broken Tempo value before it reached the cluster.

## The UIs (laptop)

Traefik serves every tool at `http://<name>.localtest.me:8080` (`*.localtest.me` always resolves to
127.0.0.1): `grafana`, `argocd`, `alertmanager`, `prometheus`, `rollouts`, plus the demo app's
Swagger UI at `orders-staging` and `orders-prod` (`/docs`). Prometheus, Alertmanager and the
Rollouts dashboard have no login, which is acceptable only because they are reachable from the
laptop alone; on EKS they would sit behind SSO or stay private.

## Lessons recorded here

- **Sync waves can deadlock.** The root app waits for each wave to be Healthy. When the Traefik
  app was stuck Progressing, root never applied the next commit, which was the fix. Unblocked by
  applying the same Application from Git by hand.
- **Charts ignore unknown values silently.** `service.type` vs `service.spec.type` left a
  `LoadBalancer <pending>` that kept Argo CD reporting Progressing. Check the rendered object.
- **Argo CD health depends on status fields.** An Ingress stays Progressing until its status has
  an address, so Traefik publishes 127.0.0.1.

> Personal lab project. Not run in production; no client code or configuration.
