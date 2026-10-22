---
title: Use cloud storage
summary: Access S3, Google Cloud Storage or Azure-backed data while keeping credentials and concurrency boundaries explicit.
status: partial
---

Granum's URL layer uses fsspec to access supported filesystems. Cloud storage can hold project records
or referenced media when the required backend and credentials exist in the process reading them.
A cloud root does not create a managed Granum service.

## Install the storage backend

From a source checkout, install the extra for your provider:

```bash
python -m pip install -e ".[service,images,s3]"
```

Use `gcs` or `azure` in place of `s3` for those providers. Configure credentials through your provider's
normal environment or machine identity. A desktop browser's cloud login is not automatically available
to a Python service or remote trainer.

## Configure a root

```bash
granum --project-root-url s3://your-bucket/granum service
```

Replace the example bucket and prefix with an accessible location. `gs://` and `az://` are corresponding
provider-backed URL schemes. Confirm read/write permissions and test a small dataset before storing
important project records there. All processes must resolve referenced media consistently; aliases
can help when local and remote paths differ.

## Serve media

The service checks media references and reads through its configured storage access. Granum currently
does not provide a browser-direct signed cloud-media URL workflow. That optimisation is
**Not yet included**; see [enterprise deployment](/docs/planned/enterprise#signed-media-delivery).
Keep credentials on the service side and limit accessible roots to the intended data.

## Concurrency and backup

Local writer locks and atomic publication do not establish distributed locking semantics for object
stores or network filesystems. Simultaneous multi-machine writes to a cloud/NFS workspace are
**Not yet included** as a supported deployment. Use a single controlled writer path or a local service
root while qualifying the actual storage environment.

Portable backup refuses unsupported cloud media and external cross-project dependencies. Materialise
required resources locally before using that workflow; provider storage snapshots have their own
consistency and restore requirements. See [operations](/docs/guides/operations).

## Remote training

A remote trainer needs the same logical data, compatible Granum installation and its own credentials.
It also needs a deliberate way to make the resulting records visible to the service. Managed remote
job orchestration is reserved in [remote environments](/docs/operate/remote).
