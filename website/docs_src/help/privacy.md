---
title: Your data and privacy
summary: What stays on your computer, what leaves it, and when.
---

Granum is local-first. By default it reads your images and writes project records on your machine.
Optional cloud roots and an explicitly configured shared service extend that boundary to the destinations
and users you choose. They are not an upload to a Granum-hosted dataset platform.

## What stays local in local-only workflows

- Your images and any copies you explicitly create through augmentation, export, backup or restore.
  Ordinary imports can reference the original files instead of copying them.
- Your annotations, and every version of them.
- Review decisions, comments and reviewer names.
- Training runs, metrics, predictions, findings and comparison reports.
- Project and dataset names, folder paths, and the contents of the log.

The core workflow does not require uploading a dataset to a Granum-hosted platform. Training libraries,
download services and already-configured third-party integrations have their own network behaviour;
inspect those separately rather than extending a local-workflow claim to the whole Python environment.

## What does leave your machine

| When | What is sent | To |
|---|---|---|
| Explicit activation/renewal in older or separately licensed builds (not required by the current alpha) | Email, machine id, app version | The licence server |
| Configured cloud storage or shared HTTPS access | Requested project/media data and authenticated operations | Your selected storage/service and authorized workspace users |
| Installing training support | A package request | PyPI |
| The first run of a model family | A request for the pretrained weights | The model's publisher |
| Framework version checks or configured experiment trackers | Requests or configured logging payloads, depending on the integration | The framework/trackers you enabled |
| Downloading Granum | Your email address, and optionally name and company, from the download form | The Granum website |

Cloud and shared workflows can transfer project contents. Do not configure destinations or accounts
that should not have access to those contents. Browser drafts also contain annotations and comments;
protect the browser profile, and avoid shared public computers.

## The local service

The dashboard talks to a service on `127.0.0.1`. It is not exposed to your network by default, it refuses
requests whose Host header it does not recognise, it refuses cross-origin writes, and it only opens files
under the roots it has been given.

Local mode has no account authentication and refuses non-loopback peers. Local machine users remain
inside its trust boundary. Wider binding requires an account registry and TLS; shared mode derives
review/edit attribution from the authenticated account and records a workspace audit log.
All shared accounts can read all projects. There is no per-project access isolation or SSO.

## Your records are yours

Every file Granum writes is a plain file in a folder you chose: JSON descriptors, Parquet rows, JSON
Lines logs. If you stop using Granum, the record of who reviewed what, which version a model was trained
on and what changed between two runs stays readable without it.

The current unrestricted alpha has no licence-expiry gate. Proprietary usage permission and any pilot
support terms are separate from that technical policy. Backups and exported drafts may contain sensitive
project information; store them with the same care as the original data.

See [Operate a pilot workspace](/docs/guides/operations) for shared-access setup, audit handling and
backup boundaries. The [course restore lesson](/docs/course/backup) demonstrates a local, byte-verified
rehearsal without claiming universal offline or cloud behaviour.
