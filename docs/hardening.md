# Operational hardening — alpha

Implemented and locally qualified in the 2 October 2026 source update. This is not an enterprise,
distributed-storage or clean-machine certification. Check an installer's build identity before
assuming it includes these changes. See [release qualification](release-qualification.md).

## 1. Exploratory versions and approved releases

1. Review and edit the working sets. Creating a dataset version records exact table revisions.
2. **Entire dataset** and **verified subset** are selection policies. Both create an **exploratory**
   version, not an approval. Historical shipments are not automatically promoted.
3. On **Datasets**, use **Approve**. Every included image must have current review evidence matching
   its row contents, schema and media SHA-256. Missing media, duplicate image references, empty sets,
   stale labels and unpinned historical reviews fail the gate.
4. Training an approved release in the dashboard requests **approved-only** training. The service
   and training subprocess both validate the release and exact input versions. The run records the
   release id and approval policy. Mixing versions from other releases is refused.
5. An exploratory run requires an explicit dashboard acknowledgment. The SDK remains available for
   deliberate exploration; it is not a global ban on unapproved training.

The SDK gate is `QaLog(project, dataset).require_approved(release_id, urls)`. The trainer also accepts
`--release-id` and `--require-approved`. A table commit resets affected images to unreviewed on the
server, regardless of the browser's follow-up requests. Exact fingerprints protect approval even if
an interrupted commit has not yet appended that reset event.

Approval is a record of reviewed contents, not a claim that labels are objectively correct. Media is
checked at approval/training startup, not made immutable for the duration of a run. Protect media from
external writers; use immutable copies/snapshots for production experiments. Local filesystem owners
and direct SDK callers are trusted and can modify unsigned logs; this is not tamper-proof attestation.

## 2. Browser recovery

The annotation editor and review inspector persist recovery copies in IndexedDB. These include shapes,
class/schema edits, undo/redo where supported, unfinished polygons and pending review comments. Writes
are acknowledged only after the IndexedDB transaction completes.

- Reopening an image in the same browser profile offers **Recover**, **Discard** and **Export**.
- A different base revision disables automatic replay. Export the draft and reconcile with the latest
  revision; do not repeatedly submit a stale edit. Export is also available after a failed server save.
- Token-checked transactions prevent one tab from overwriting or deleting another tab's newer draft.
- Server failures retain the draft. A confirmed server commit clears it; a cleanup failure is reported
  separately and does not turn an acknowledged commit into an apparent failed write.
- Editors block changes while a save is in flight. Pending review comments must be posted or cleared
  before committing box changes, so a failed comment is not silently discarded.

Drafts are **not** a server backup or cross-device sync. Clearing browser/site data, private browsing,
profile loss, quota failures or an OS crash before the transaction completes can lose unacknowledged
changes. Storage failure is shown explicitly; export before leaving if saving to the service is not
possible. Protect exported JSON and the browser profile as sensitive project data.

## 3. Local versus authenticated shared access

Default local service accepts only loopback peers. Host/Origin/path checks remain defense in depth,
not account authentication. Local author names remain self-reported.

Shared access is **one workspace**. Every account can read every project, image, run and job visible
to that service. There is no per-project tenancy, SSO, user assignment or managed hosting.

| Role | Writes allowed |
|---|---|
| Viewer | None; read-only analysis requests remain available |
| Annotator | Annotation commits, comments, tags, saved views, exploratory versions |
| Reviewer | Annotator actions plus review decisions/approval, recoverable curation, training and analysis jobs |
| Administrator | All routes, including installation, service management and permanent deletion |

The service overrides submitted author names with the authenticated account. Legacy review decisions
and annotation producers are also attributed. Jobs copy request context into their worker thread;
authentication is not a substitute for filesystem ownership or a per-job tenancy model.

### Provisioning

Store the registry and TLS private key **outside project data, scan roots and project backups**.
Create the administrator first. Passwords are prompted invisibly and stored only as salted scrypt hashes.
Never put passwords in command arguments, URLs, source files or chat.

```sh
granum access add-user admin --role admin --file /secure/granum-users.json
granum access add-user reviewer --role reviewer --file /secure/granum-users.json
granum --project-root-url /srv/granum service --host 0.0.0.0 \
  --auth-file /secure/granum-users.json \
  --tls-cert /secure/granum-cert.pem --tls-key /secure/granum-key.pem \
  --allow-host granum.example.org
```

Use a certificate trusted by the clients. HTTP Basic credentials are accepted **only over HTTPS**;
they are handled by the browser, not stored by dashboard JavaScript. Non-loopback startup without
authentication and native TLS fails closed. A loopback-only service can sit behind a trusted TLS
reverse proxy; forwarded headers are trusted only from loopback. Do not expose its HTTP backend.

POSIX registries must be owner-only; protect Windows files with appropriate NTFS ACLs. Changes and
revocations require a service restart. Browsers may cache Basic credentials; closing a browser is not
an administrative revocation. Review/cancel already-running jobs separately when revoking access.
Use a VPN/firewall for shared deployments; internet-scale identity/security operation is not qualified.

### Audit failures

Shared mutations append request/completion records to `access-audit.jsonl` at the workspace root,
without credentials. Failure to record the request prevents mutation. If completion logging fails
after a mutation, the actual result is preserved, a warning and request id are returned, and further
writes are blocked. Inspect the recorded request and project state, repair storage, then restart.
An interrupted request with no completion event has an unknown outcome: investigate before retrying.
The log is not cryptographically signed or resistant to a filesystem administrator.

## 4. Local durability, conflicts and retries

- Local writers use reentrant cross-process file locks. Keep all writers on the same workspace
  configuration. This is not a distributed lock for S3/GCS/Azure, NFS or network shares.
- Local bytes use a same-directory temporary, fsync and atomic replacement. New directory entries are
  synced on POSIX. Windows replacement is atomic, but directory fsync is not exposed by this implementation.
- Table names are reserved exclusively. Parquet is written before object metadata; metadata is the
  publication marker. An interrupted reservation is left unindexed, not reused or overwritten.
- Tables are immutable. Run parameter/scalar updates merge under a writer lock.
- Review/tag logs repair only an incomplete final record. Interior corruption is refused rather than
  skipped. Preserve the damaged file and restore from backup; do not erase evidence to make a write pass.
- Browser commits include `expected_head`; shared API clients must supply it. A conflicting revision
  returns 409 and leaves the browser draft intact. Identical commit retries return the existing child
  revision and repair any missing review-reset event. Deliberate local SDK/API branching is still possible.

Fault-injection tests cover interruption and retries; they do not emulate every disk controller,
filesystem, kernel crash or Windows power-loss scenario. Orphan reservations have no automatic cleanup
command; inspect offline and retain evidence before removing only proven uncommitted directories.

## 5. Media integrity

```sh
granum integrity snapshot my-project --output /backups/media-baseline.json
granum integrity verify /backups/media-baseline.json
```

The baseline hashes media referenced by project versions, not just current rows. Verification reports
changed/missing files without moving or overwriting them. It is diagnostic, not a background monitor.
Reviewing a selection hashes only its selected media; approval and approved-only startup recheck the
whole included release. Large images or remote media can make those checks expensive.

## 6. Backup, restore and upgrade rehearsal

Stop the service, training jobs and other project/media writers before a snapshot. Put the archive
outside the source project and protect it; ZIP snapshots are not encrypted.

```sh
granum --project-root-url /srv/granum backup create my-project --output /backups/my-project.zip
granum --project-root-url /srv/granum-rehearsal backup restore /backups/my-project.zip --name restored-check
```

Supported snapshots contain local project records, referenced local media and recorded run weights.
External media is copied by content hash. Checksums, names, entries and sizes are verified in hidden
staging, references are relocated, and only then is the project published. Existing targets are never
overwritten. Unknown backup/object formats, unsafe paths, symlinks and checksum mismatches are refused.

Limits: 200,000 files, 32 MiB manifest, default 100 GiB expanded restore (`--max-gib` can be raised).
Cloud media and external table/cross-project dependencies must be materialized first or the snapshot
is refused. Python/CUDA environments, training caches, arbitrary external artifacts, the workspace-wide
audit log and the account registry are **not** a complete system backup. Back those up separately.
Restoring a large Parquet file currently materializes its rows and can require substantial RAM.

For an upgrade: retain the old app and an offline snapshot, restore into a disposable separate root,
verify image bytes/review logs/releases/run references, then test read/edit/approval/training selection.
Unversioned legacy objects are read as format 1; future formats fail explicitly. Do not assume older
applications can read future formats. The original project remains your rollback; no automatic in-place
schema migration is claimed. Unusual non-media path fields may require re-review after relocation.

## Qualification boundary

Local automated tests include concurrent writers, interrupted publication, stale commits, exact-content
approval, changed/missing media, portable restore and real-browser editor reload/failed saves. See
[scale measurements](scaling.md) and [release qualification](release-qualification.md).

The [guided course](https://granum.app/docs/course/start) additionally records real Linux YOLO26 nano
GPU jobs at 3 and 12 epochs on a 96/24-image subset, plus a stopped-writer backup and separate restore
with all 120 image hashes/sizes matching. Those measured models were poor; this is narrow workflow
evidence, not qualification of every GPU/framework/installer. Windows clean-machine operation, public
deployment, live email/payments and enterprise controls still need separate evidence. Passing source
tests or a course recording alone does not make an alpha generally available.