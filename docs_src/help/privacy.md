---
title: Your data and privacy
summary: What stays on your computer, what leaves it, and when.
---

Granum is a desktop application. It reads your images from where they already are, writes its own records
beside them, and serves a dashboard to a window on the same machine. That is the whole architecture, and
it is the reason the privacy answer is short.

## What never leaves your machine

- Your images. Granum records their paths and reads them; it never copies them anywhere but into your own
  augmented dataset versions.
- Your annotations, and every version of them.
- Review decisions, comments and reviewer names.
- Training runs, metrics, predictions, findings and comparison reports.
- Project and dataset names, folder paths, and the contents of the log.

There is no telemetry, no crash reporting, no usage analytics, and no "anonymous statistics" setting,
because there is nothing to switch off.

## What does leave your machine

| When | What is sent | To |
|---|---|---|
| Signing in, and while renewing a licence | Your email address, this computer's machine id, the app version | The Granum licence server |
| Installing training support | A package request | PyPI |
| The first run of a model family | A request for the pretrained weights | The model's publisher |
| Downloading Granum | Your email address, and optionally name and company, from the download form | The Granum website |

Nothing in that list includes a project name, a file path, an image or a label.

## The local service

The dashboard talks to a service on `127.0.0.1`. It is not exposed to your network by default, it refuses
requests whose Host header it does not recognise, it refuses cross-origin writes, and it only opens files
under the roots it has been given.

It has **no authentication**. Anyone who can reach that port — anyone with an account on that machine, or
anyone on the network if you deliberately bind it wider — can read and change everything in it. Treat the
service as a part of your desktop session, not as a server.

## Your records are yours

Every file Granum writes is a plain file in a folder you chose: JSON descriptors, Parquet rows, JSON
Lines logs. If you stop using Granum, the record of who reviewed what, which version a model was trained
on and what changed between two runs stays readable without it.

When a licence expires, the app turns read-only rather than locking. Reading and exporting your own data
never requires a payment.
