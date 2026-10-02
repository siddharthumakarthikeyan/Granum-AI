---
title: 11. Back up, restore and share safely
summary: Stop writers, verify media, create a portable project snapshot and inspect a separate restored workspace before trusting the backup.
---

**Goal:** show that project records and media can be restored independently of their original paths.
Complete [the handoff lesson](/docs/course/handoff) first. This exercise is local filesystem recovery,
not cloud disaster-recovery or power-loss qualification.

## What we are protecting, and why export is not enough

An export gives another tool images and labels. A **project backup** also preserves supported Granum
project records, reviews, version references, releases, runs and recorded weights. It checksums the
included files and copies referenced local media into the portable snapshot.

A **media integrity snapshot** records image hashes so verification can report changed or missing
bytes. It diagnoses differences; it does not restore a missing file or continuously monitor the disk.

## Step 1: stop writers and choose destinations

1. Finish or intentionally cancel all import, training, annotation and export jobs.
2. Save or export any pending browser drafts. Drafts are not in the project archive.
3. Stop the service and other programs that write project records or referenced media. On a Linux
   systemd installation this can be `systemctl --user stop granum`; a foreground service can be stopped
   with Ctrl+C. Merely closing the browser does not necessarily stop the service.
4. Choose a protected backup directory **outside the source project**. ZIP backups are not encrypted.
5. Choose a new, separate rehearsal project root. Never test restoration by overwriting your only copy.

The commands below assume a Linux course project in `~/granum` and use `~/granum-backups` and
`~/granum-rehearsal` as examples. Substitute your actual roots. Global options go before the subcommand.
Run them in an environment where the intended Granum CLI is available.

## Step 2: record and verify media integrity

```bash
mkdir -p "$HOME/granum-backups"
granum --project-root-url "$HOME/granum" integrity snapshot aerial-walkthrough \
  --output "$HOME/granum-backups/aerial-media.json"
granum integrity verify "$HOME/granum-backups/aerial-media.json"
```

For a fresh, unchanged course workspace, the expected report is **120 checked, no changed files, no
missing files**. The command refuses to overwrite an existing snapshot; use a new dated name rather
than destroying the old baseline. Keep the old report if it identifies unexpected changes.

This manifest checks media referenced by project versions, not merely the currently visible gallery.
Do not store it in a location accessible to unrelated users: it contains paths and file identities.

## Step 3: create the project backup

```bash
granum --project-root-url "$HOME/granum" backup create aerial-walkthrough \
  --output "$HOME/granum-backups/aerial-walkthrough.zip"
```

Read the returned archive path, file count, byte count and SHA-256. The recorded exercise produced
**205 files**, a **37,825,567-byte archive**, and **122 media entries**. The latter includes the two
recorded weight files; the dataset still has 120 images. Your archive can differ if you repeated edits,
skipped training or created additional records.

The [actual backup/restore receipt](/assets/course/operations-evidence.json) preserves the observed
counts and checksum. The project archive itself is not the public sample download.

## Step 4: restore into a separate workspace

```bash
granum --project-root-url "$HOME/granum-rehearsal" backup restore \
  "$HOME/granum-backups/aerial-walkthrough.zip" --name aerial-restored
granum --project-root-url "$HOME/granum-rehearsal" integrity snapshot aerial-restored \
  --output "$HOME/granum-backups/aerial-restored-media.json"
granum integrity verify "$HOME/granum-backups/aerial-restored-media.json"
```

Restore checks entries and checksums in staging, relocates supported references and publishes the
project only after validation. It refuses existing targets, unsafe paths and unsupported future formats.
If it refuses an archive, preserve the evidence rather than editing its manifest to force acceptance.

The original and restored integrity manifests have different path keys. Compare **hashes and sizes**,
not literal paths. In the recorded rehearsal, all 120 image hashes and sizes matched, and every restored
image reference was inside the separate rehearsal root.

## Step 5: open and inspect the restored project

Start a separate local service explicitly pointed at the rehearsal root, on an unused port:

```bash
granum --project-root-url "$HOME/granum-rehearsal" service \
  --host 127.0.0.1 --port 18862
```

Open `http://127.0.0.1:18862` and select **aerial-restored**. Do not accidentally inspect the original
workspace's dashboard tab and call that a restore check.

1. Confirm the restored project opens.
2. Open Images, confirm 120 and inspect actual loaded media.
3. Inspect review comments and the two-image verified selection.
4. Open Datasets: the full baseline should remain exploratory; the two-image excerpt should retain
   its approval state when its portable contents still match.
5. If you trained, check the two run records and relocated recorded-weight paths. A successful file
   restore does not reinstall the Python/CUDA runtime needed to use them.
6. Stop the rehearsal service when done. Keep the original project as your rollback copy.

<figure class="doc-figure">
<a href="/assets/course/32-restored-project.webp"><img src="/assets/course/32-restored-project.webp" alt="Actual aerial-restored project opens from the separate restored workspace after offline backup and restore." width="1440" height="960" loading="lazy"></a>
<figcaption>The project name and workspace are different from the source. The commands completed before this UI recording.</figcaption>
</figure>
<figure class="doc-figure">
<a href="/assets/course/33-restored-images.webp"><img src="/assets/course/33-restored-images.webp" alt="Actual restored gallery loads the course images from relocated, content-addressed media paths." width="1440" height="960" loading="lazy"></a>
<figcaption>Portable media may have content-hash filenames after relocation. Confirm content and identity, not an unchanged path string.</figcaption>
</figure>
<figure class="doc-figure">
<a href="/assets/course/34-restored-approval.webp"><img src="/assets/course/34-restored-approval.webp" alt="Restored Datasets page retains the exploratory baseline and approved two-image excerpt." width="1440" height="960" loading="lazy"></a>
<figcaption>Check meaningful project state as well as the archive's “verified” result.</figcaption>
</figure>

## Watch the restored workspace

<figure class="doc-figure doc-video">
<video controls preload="none" playsinline poster="/assets/course/32-restored-project.webp" aria-label="Recorded inspection of the actual restored workspace, images and approval state" aria-describedby="restore-video-caption">
<source src="/assets/course/10-restore.mp4" type="video/mp4"><track kind="captions" src="/assets/course/10-restore.vtt" srclang="en" label="English" default>
<a href="/assets/course/10-restore.mp4">Download the recording</a>.
</video><figcaption id="restore-video-caption">17 seconds · silent, with captions · the restored UI, not a recording of the offline CLI commands.</figcaption>
</figure>
<details class="doc-transcript"><summary>Read the video transcript</summary>
<ol><li>The offline backup and restore commands finished before recording; this is the separate restored project.</li><li>Open restored media. All 120 hashes were checked and references now point inside the rehearsal workspace.</li><li>Check the exploratory baseline and approved two-image excerpt. Verifying a restore is stronger evidence than merely creating a ZIP.</li></ol>
</details>

## What is not a complete system backup?

The supported project archive does not recreate the application, Python/CUDA environment, all training
caches, arbitrary external artifacts, browser drafts, workspace-wide audit log or account registry.
Cloud media and cross-project/external table dependencies must be materialised first or backup may be
refused. Protect those other records separately. Keep account registries and TLS private keys **outside
project/media roots and project backups**.

## Sharing is an explicit security decision

Do not expose the default local HTTP service to a network. Authenticated shared access requires
appropriate HTTPS/TLS, accounts and role assignment. **Every shared account can read every project
visible in that service workspace.** There is no per-project tenancy or SSO.

- **Viewer:** read-only access.
- **Annotator:** annotation and collaboration writes, not approval/training authority.
- **Reviewer:** review decisions, approval and supported model/analysis jobs.
- **Administrator:** all service actions, including permanent deletion and management.

Local author names are self-reported. Shared-mode attribution comes from the authenticated account.
For the exact setup, revocation, audit-failure procedure and limits, use
[Operate a pilot workspace](/docs/guides/operations), not a port-forwarding shortcut.

## What we learn

A trustworthy backup process includes a quiescent source, an external archive, a fresh restore and
meaningful verification. An unchanged integrity result is evidence about those bytes at that time,
not protection from future mutation or a guarantee against every hardware failure.

## Checkpoint

You have retained the original, checked restored image bytes and inspected the restored project.
Next: [apply the workflow to your own data](/docs/course/next).

## If something differs

| Symptom | What to do |
|---|---|
| Snapshot already exists | Use a new name; do not overwrite the previous evidence |
| Changed or missing media | Identify the writer/location change; restore intended bytes or re-review new contents |
| Restore target exists | Choose a fresh name/root, not an overwrite |
| Checksum or format refusal | Preserve the archive/error; obtain a valid compatible backup or the matching app version |
| Restored project opens but media does not | Verify relocated references and byte hashes; project metadata alone is insufficient |
| Shared write reports audit failure | Inspect actual committed state before retrying; repair storage and restart according to the operations guide |