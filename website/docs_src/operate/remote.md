---
title: Remote and container environments
summary: Plan remote data access and find the current boundary for notebooks, containers and managed training.
status: partial
---

Granum can be run from a Python environment on another machine, but that machine's filesystem,
credentials and network addresses are separate from those of your browser. Start by deciding where
project records, source media, model weights and the service will live.

## Supported building blocks

Use the [service](/docs/operate/service) on the machine that can read the data. Connect a browser through
an intentionally configured [shared HTTPS deployment](/docs/operate/shared). A training process uses
its configured project root and supported [framework integration](/docs#integrations).

A browser URL containing `localhost` addresses the browser's machine. A remote service also cannot
read a dataset merely because it exists on the laptop showing the dashboard. Check the data path from
the service and trainer independently.

Cloud-backed URLs can help share data locations, subject to the [cloud storage limits](/docs/operate/cloud).
Use consistent class maps, aliases and source revisions on both machines. A local metadata copy must
still reference media that exists at the resolved destination.

## Docker and Kubernetes

**Not yet included.** There is no qualified container image, Compose stack, Helm chart or Kubernetes
operator supplied as a complete Granum deployment. This section is reserved for persistent volumes,
service identity, TLS, GPU access, health checks, upgrade/rollback and single-writer rules.

Running Python in a container yourself does not establish those operational guarantees. Retain the
same service access checks and explicitly mount the records and media your workload requires.

## Hosted notebooks

**Not yet included.** Turnkey Google Colab and AWS SageMaker connection guides, managed tunnels and
persistent notebook lifecycle integration are reserved. The Python SDK can be installed in a
compatible environment, but temporary notebook disks, browser reachability and disappearing processes
remain your environment's responsibilities.

## Remote jobs

**Not yet included.** Managed worker registration, remote queues, scheduling and resource assignment
are reserved under [compute](/docs/planned/compute). A dashboard training job currently runs through
the configured service's supervised model process. Starting it does not schedule an independent
cloud training fleet.

For the supported local deployment, follow the [guided course](/docs/course/start). Qualify a custom
remote setup on a separate workspace before transferring the only copy of a project.
