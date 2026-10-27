# sentinel-gitops

[![validate](https://github.com/sudhanshu5439/sentinel-gitops/actions/workflows/validate.yml/badge.svg)](https://github.com/sudhanshu5439/sentinel-gitops/actions/workflows/validate.yml)

The desired state of the [Sentinel](https://github.com/sudhanshu5439/sentinel) platform. Argo CD
watches this repo and keeps the cluster identical to it. Nobody runs `kubectl apply` by hand.

```
bootstrap/root.yaml        the only object applied manually ("app of apps")
argocd/                    Argo CD Applications: Kyverno, policies, staging, prod
platform/policies/         Kyverno admission policies
apps/base/                 the Sentinel services, environment-agnostic
apps/overlays/staging/     auto-promoted by CI on every merge to main
apps/overlays/prod/        promoted only through a reviewed pull request
tests/policies/            manifests the policies must reject
scripts/validate.sh        render + schema check + policy tests (also run in CI)
```

## How a release reaches production

1. A change merges to `main` in the `sentinel` repo.
2. CI builds, scans, signs and attests the images, then commits their **digests** to
   `apps/overlays/staging`. Argo CD syncs staging within minutes.
3. CI opens a pull request here that updates `apps/overlays/prod` to the same digests.
4. A human reviews and merges it. Argo CD syncs prod.
5. In both namespaces, Kyverno admits a pod only if every Sentinel image is referenced by digest
   and signed by `supply-chain.yml` on `main`, comes from an allowed registry, and declares
   resources and a readiness probe.

Rolling back = reverting a commit in this repo.

> Personal lab project. No client code or configuration.
