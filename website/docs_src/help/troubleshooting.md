---
title: Troubleshooting
summary: The service, the window, training, imports and licences, when they do not behave.
---

## The dashboard says the service is not reachable

The app is two parts: a background service and a window. The window is telling you the service is not
answering.

```bash
granum app status                  # is it running, on which port, with which project root?
systemctl --user restart granum    # Linux
tail -50 ~/.local/state/granum/service.log
```

On Windows, restart Granum from the Start menu; the service starts with it.

If the port is taken by something else, change it: `granum app install --port 8100`.

## The window opens blank, or not at all

Granum's window needs WebKitGTK on Linux. If it is missing the app falls back to your browser and says
so; install it with `sudo apt install python3-gi gir1.2-webkit2-4.1`. You can always use the dashboard
in a browser at `http://127.0.0.1:8000`, or `granum open --browser`.

## Import cannot see my folder

The service only reads under its configured data roots — your home folder by default. A dataset on
another disk needs that path added:

```bash
granum service --data-root /mnt/datasets    # or set service.data-roots in the config
```

## Preflight is very slow

It is decoding every image, which is the thorough setting. For a dataset you have imported before,
choose **Sample, 200 per set**, or **Annotations only** when the images live on slow or remote storage.

## Training

**"Training support is not installed"** — the first Train dialog offers to install PyTorch; it needs the
internet once and about 3 GB.

**Out of memory** — reduce the image size first, then the model size. RT-DETR large needs roughly 8 GB of
graphics memory at batch 8.

**"Another training job is running"** — one job per machine. Wait, or cancel the other from the Runs
screen.

**The run finished but Findings is empty** — three possible reasons, and the page says which: the run did
not record predictions each round, it was cancelled before producing any, or the model never became
competent on that set. The last is common on short schedules; train longer.

**The run stopped when I restarted the service** — training survives a restart on current versions, but
check `granum app status` before restarting anything while a job is running.

## Licence

The current unrestricted alpha does not enforce licence expiry. The messages below apply only to an
older or explicitly licensed build. First record `granum build-info` and confirm the installed channel.

**"Read-only"** — on a licensed build, the plan or offline lease may have expired. Contact support for
that release. Your data is untouched; only changes are refused.

**"This licence is for another computer"** — keys are issued per machine. Sign in on this machine to get
its own, freeing a slot elsewhere with **Sign out** if the plan is full.

**"The system clock is behind"** — Granum counts offline time against the latest time it has seen.
Correct the clock and it resumes.

## Images do not appear

Projects record absolute paths to your images. If the files moved, the dataset points at nothing. Move
them back, or re-import from the new location. Granum never copies your images, which is why it cannot
fix this for you.

## Still stuck

Collect the version and the log before asking for help:

```bash
granum version
granum app status
tail -200 ~/.local/state/granum/service.log
```

The log holds paths and project names but no image content.
