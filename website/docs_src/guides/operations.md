---
title: Operate a pilot workspace
summary: Approval, browser recovery, authenticated shared access, audit failures, integrity checks, portable backups and safe upgrade rehearsal.
---

This guide is for the person responsible for keeping a pilot workspace usable and recoverable.
For a worked example with real results, follow [the aerial course](/docs/course/start), especially
[review/recovery](/docs/course/review), [approval/export](/docs/course/handoff) and
[backup/restore](/docs/course/backup).

## Approval is an explicit gate

Creating a dataset version—entire dataset or verified subset—creates an **exploratory** version.
Use **Datasets → Approve… → Check and approve** to approve exact contents. Every included image must
have matching review evidence for its row, schema and media bytes. Empty sets, stale reviews,
duplicate image references, missing media and changed contents can fail the gate.

Approved-only training validates release membership and approval in both the service and the training
process. Exploratory dashboard training requires acknowledgement. Direct SDK callers remain trusted
and may deliberately explore; approval is not a blanket ban on all unapproved Python experiments.

Approval records review evidence, not objective label truth. It checks media at approval/startup,
not continuously for the entire run. Protect media against external writers. Local logs are unsigned
and filesystem administrators can modify them; this is not tamper-proof attestation.

## Browser recovery and stale saves

The annotation editor and review inspector store recovery copies in **IndexedDB**. Wait for the
storage acknowledgement. Recover in the same browser profile and origin; a new port, desktop profile
or private session may have different storage.

- A matching base can be recovered; a different base disables automatic replay.
- On conflict, retain/export the draft, open the latest revision and reconcile explicitly.
- Server save failure keeps the draft. A confirmed server commit is not undone merely because browser
  cleanup failed; read the separate warning before retrying.
- Export drafts before clearing site data, reinstalling a browser profile or abandoning a failed save.
- Browser drafts contain potentially sensitive annotations/comments. They are not server backups or
  cross-device synchronization.

The service rejects stale shared commits. Identical supported commit retries reuse the committed child
revision; arbitrary manual retries after an ambiguous failure still require state inspection.

## Local mode versus shared mode

Default local mode accepts loopback peers only. Host, Origin and path checks are defence in depth,
not a login system. Local author names are self-reported and local filesystem users are trusted.

Shared mode is **one whole workspace**. Every account can read every project, media item, run and job
visible to that service. There is no per-project access isolation, SSO, managed hosting or user-assignment
system. Use separate workspaces/services if datasets must not be visible to the same readers.

| Role | Writes allowed |
|---|---|
| Viewer | None; read-only analysis requests remain available |
| Annotator | Annotation commits, comments, tags, saved views and exploratory versions |
| Reviewer | Annotator actions plus review/approval, recoverable curation and supported training/analysis jobs |
| Administrator | All routes, including management, installation and permanent deletion |

Shared requests derive authors from the authenticated account, overriding submitted names. Do not
equate this with protection against an administrator who directly edits filesystem records.

## Provision shared access deliberately

Keep the account registry and TLS private key **outside all project/media scan roots and backups**.
Use a certificate trusted by clients and restrict network exposure with a firewall or VPN. The following
uses illustrative administrator-owned paths and a hostname you must replace with your actual setup.

```bash
granum access add-user admin --role admin --file /secure/granum-users.json
granum access add-user reviewer --role reviewer --file /secure/granum-users.json
granum --project-root-url /srv/granum service --host 0.0.0.0 \
  --auth-file /secure/granum-users.json \
  --tls-cert /secure/granum-cert.pem --tls-key /secure/granum-key.pem \
  --allow-host granum.example.org
```

Passwords are prompted invisibly and stored as salted scrypt hashes. Never put them in command-line
arguments, URLs, source files or support chat. HTTP Basic credentials must travel over **HTTPS**.
Non-loopback startup without the required authentication/TLS fails closed. A loopback backend behind a
trusted TLS proxy must not also be exposed as unauthenticated HTTP; forwarded headers are trusted only
from loopback.

POSIX registry files must be owner-only; on Windows use appropriate NTFS permissions. Account changes
and revocations require a service restart. A browser may cache Basic credentials; closing its window
is not administrative revocation. Review or cancel already-running jobs separately.

## Handle an audit failure without duplicating work

Shared mutations append request and completion records to the workspace audit log. If the request
cannot be recorded, mutation is refused. If completion logging fails **after** a change was committed,
the service preserves the real result, returns a warning/request identifier and blocks subsequent writes.

1. Retain the error, request ID and operation details.
2. Inspect project state to determine whether the operation committed.
3. Preserve the audit log; do not delete it to clear the warning.
4. Repair the storage/permission problem and restart the service.
5. Reconcile an interrupted request with no completion record before deciding whether to retry.

The log does not include credentials, but it can contain sensitive project/operation information.
Back it up separately with suitable permissions; it is not a cryptographically signed record.

## Media integrity and portable backup

Stop service, model jobs and other project/media writers before a snapshot. Use a destination outside
the source project. The following is the same workflow used in the course, with generic project names:

```bash
granum --project-root-url /srv/granum integrity snapshot my-project --output /backups/media.json
granum integrity verify /backups/media.json
granum --project-root-url /srv/granum backup create my-project --output /backups/my-project.zip
granum --project-root-url /srv/granum-rehearsal backup restore /backups/my-project.zip --name restored-check
```

Integrity verification reports changed/missing bytes without replacing them. Baseline manifests are
not overwritten. Portable backup includes supported local project records, local referenced media and
recorded weights. Restore validates checksums/names/sizes in staging, relocates supported references
and refuses an existing target.

Limits include **200,000 files**, a **32 MiB manifest** and a default **100 GiB expanded restore**;
`--max-gib` can raise the last limit. Large Parquet relocation can require substantial RAM. Cloud media
and external table/cross-project dependencies must be materialised first or backup is refused. Archives
are not encrypted.

A project archive is not a complete system backup: separately protect app artifacts, Python/CUDA
environments, relevant external outputs, training caches, browser drafts, workspace audit logs and
credentials. Preserve access controls when transferring backups.

## Rehearse an upgrade and rollback

1. Retain the current application artifact, its build identity and an offline project snapshot.
2. Restore into a disposable separate root with the candidate build.
3. Verify media hashes, images, reviews, release contents and run/weight references.
4. Test read/edit/recovery and intended approval/training selection there—not on the only original.
5. Keep the original unchanged as rollback until qualification is complete.

Future object formats are refused explicitly. Do not assume an older application can read records
written by a newer one; no universal automatic in-place schema migration is promised. Unusual non-media
path fields may require re-review after relocation.

## Know the qualification boundary

Local writer locks and atomic publication are not distributed locks for cloud stores, NFS or network
shares. Interrupted-record tests do not emulate every filesystem, disk controller or power loss.
Some large operations remain materialising rather than streaming; consult [measured limits](/docs/reference/limits).

The course demonstrates a small Linux source workflow, real YOLO GPU jobs and one local restore.
Qualify your exact installer, OS, GPU, storage, access setup and workload before promising them to a pilot.