---
title: Managed compute and plugins
summary: Reserved space for a compute service, plugin catalogue and automated model workflows.
status: planned
---

**Not yet included.** Granum has local model jobs, optional training support and Python integrations.
A managed compute platform and public plugin system are planned separately from those existing paths.

## Compute service

Reserved capabilities include worker registration, resource selection, remote queues, scheduling,
retry rules, job ownership and environment isolation. A complete guide will explain how a request
moves from the dashboard to a worker and how results are attached to exact data versions.

Today, use [service-supervised jobs](/docs/operate/service) and inspect their logs and status. A local
training process continuing after a service restart does not imply remote scheduling or cluster failover.

## Plugin SDK and catalogue

**Not yet included:** a public plugin manifest, compute interface, UI contribution contract, package
builder, version-compatibility rules and a trusted plugin catalogue. There is no supported install,
update or uninstall flow for arbitrary community compute plugins.

This section reserves space for plugin authoring, private catalogue registration, environment health,
logs, dependency resolution and installation policies. When implemented, it will include one complete
plugin and its test/deployment procedure. Granum's current training add-on is an existing dependency
installation path, not a general plugin marketplace.

## Automatic labelling pipelines

**Not yet included:** unattended dataset-wide SAM segmentation, model-assisted active-labelling queues,
automatic dataset-growth schedules and a built-in pipeline for training crop classifiers then attaching
per-instance embeddings.

Use [Pre-label](/docs/improve/prelabel) for supported model drafts and [SAM](/docs/improve/sam) for
interactive image-level proposals. Review suggestions, create a new dataset version, train and compare
explicitly. These manual stages preserve an inspectable record while the orchestration is reserved.

## Hyperparameter jobs

**Not yet included:** a managed sweep scheduler with resource budgets and automatic candidate selection.
Runs already store hyperparameters, metrics and the source versions used. You can run your own
experiment driver and attach each result through [Python runs](/docs/python/runs).

The future compute guides will document cancellation, resource limits, recovery and credential scope
alongside launch instructions. Until those contracts exist, this page deliberately supplies no
placeholder CLI commands or configuration keys.
