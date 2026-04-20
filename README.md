# oom-autofix-operator

[![Artifact Hub](https://img.shields.io/endpoint?url=https://artifacthub.io/badge/repository/oom-autofix-operator)](https://artifacthub.io/packages/search?ts_query_web=oom-autofix-operator)

## Chart layout

```text
oom-autofix-operator/
├── README.md
└── charts/
    └── oom-autofix-operator/
        ├── Chart.yaml
        ├── values.yaml
        ├── .helmignore
        ├── files/
        │   └── operator.py    # Source for ConfigMap data key operator.py
        └── templates/
            ├── _helpers.tpl
            ├── configmap.yaml
            ├── deployment.yaml
            ├── rbac.yaml
            ├── serviceaccount.yaml
            └── test-stress.yaml
```

Helm chart for the **OOM AutoFix Operator**: a [Kopf](https://kopf.readthedocs.io/)-based Python controller that watches Pods for `OOMKilled` terminations and raises the owning Deployment’s memory limit (for example **400Mi → 900Mi** using the default `scaleFactor` of **2.25**).

> **Warning:** This chart binds the operator `ServiceAccount` to the built-in **`cluster-admin`** `ClusterRole` for quick demos. **Do not use this RBAC model in production.** Prefer least-privilege `Role`/`ClusterRole` rules that only allow `get/list/watch` on Pods and `patch` on Deployments.

## Prerequisites

- Kubernetes **1.24+**
- Helm **3.x**

The Helm chart lives under **`charts/oom-autofix-operator/`**, not the repo root. From the repository root, use that path (or `cd` there) for `helm lint` / `helm package`:

```bash
helm lint charts/oom-autofix-operator
helm package charts/oom-autofix-operator
```

## Install

```bash
helm upgrade --install oom-autofix ./charts/oom-autofix-operator \
  --namespace oom-autofix --create-namespace
```

### Optional: Prometheus URL (reserved)

```bash
helm upgrade --install oom-autofix ./charts/oom-autofix-operator \
  --namespace oom-autofix --create-namespace \
  --set prometheusUrl=http://prometheus-kube-prometheus-prometheus.monitoring:9090
```

The URL is exposed to the operator as `PROMETHEUS_URL` for future metrics integrations.

## Configuration

| Parameter | Description | Default |
|-----------|-------------|---------|
| `scaleFactor` | Multiplier applied to the current memory limit (MiB) to compute the new limit | `2.25` |
| `maxMemoryGi` | Upper cap for the new limit (GiB) | `2` |
| `containerName` | Container name inside the target Deployment to patch | `app` |
| `logLevel` | Python logging verbosity (`>=8` enables DEBUG-style verbosity) | `8` |
| `prometheusUrl` | Optional Prometheus base URL (env `PROMETHEUS_URL`) | `""` |
| `testStress.enabled` | Deploy demo stress workload with **400Mi** limit | `true` |

See `values.yaml` for image, resources, and scheduling options.

## Demo

1. Install the chart (see above). With defaults, a **stress** Deployment is created with a **400Mi** memory limit.
2. Wait for the stress Pod to exceed memory and be **OOMKilled** (container name matches `containerName`, default `app`).
3. Watch operator logs:

   ```bash
   kubectl logs -n oom-autofix -l app.kubernetes.io/name=oom-autofix-operator -f
   ```

   You should see messages such as **🔔 OOM DETECTED**, **✅ PATCHED to …Mi**, and **🚀 ACTIVE** on startup.
4. Confirm the Deployment was patched:

   ```bash
   kubectl get deploy -n oom-autofix -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.spec.template.spec.containers[0].resources.limits.memory}{"\n"}{end}'
   ```

5. Disable the bundled stress test when you no longer need it:

   ```bash
   helm upgrade oom-autofix ./charts/oom-autofix-operator --set testStress.enabled=false
   ```

## Screenshots (Artifact Hub / docs)

Add PNGs under `docs/screenshots/` and reference them from your Artifact Hub package or docs site:

| File | Suggested content |
|------|-------------------|
| `docs/screenshots/01-helm-install.png` | Terminal showing `helm upgrade --install` success |
| `docs/screenshots/02-operator-logs.png` | `kubectl logs` with 🔔 / ✅ / 🚀 lines |
| `docs/screenshots/03-deployment-patched.png` | `kubectl describe deploy` or YAML showing raised `limits.memory` |

Example markdown (after you add images):

```markdown
![Helm install](docs/screenshots/01-helm-install.png)
```

## Artifact Hub

This chart includes `artifacthub.io/*` annotations in `Chart.yaml` (category, license, links, image hint). To publish:

1. Push the chart to an OCI registry or Helm HTTP repo.
2. [Create an Artifact Hub repository](https://artifacthub.io/docs/topics/repositories/helm-charts/) pointing at that repo.
3. Optionally add a `artifacthub-repo.yml` at the repository root (see [Artifact Hub metadata](https://artifacthub.io/docs/topics/annotations/helm/)).

Replace `https://github.com/example/oom-autofix-operator` in `Chart.yaml` with your real source URL before publishing.

## Uninstall

```bash
helm uninstall oom-autofix -n oom-autofix
```

## License

Apache-2.0 (see `Chart.yaml` annotations).

## Maintainer

- **Sanket Gawali** — sanket@example.com
