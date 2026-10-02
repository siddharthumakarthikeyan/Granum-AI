---
title: Install Granum
summary: Check build provenance, install the platform artifact, verify the running service, and understand optional training dependencies.
---

Granum is a desktop application and local service. Packaged artifacts bundle the core Python runtime,
libraries and dashboard; training support is installed separately. Platform window, filesystem and GPU
requirements still matter. Start with the [guided aerial course](/docs/course/start) for a complete
first-use path with a real sample, screenshots and videos.

## Before you install

Use the [download page](/download) or an artifact supplied by the authorized pilot maintainer. Confirm
the platform, source revision, build manifest and SHA-256. Do not infer that an old file includes current
features merely because its version is also 0.1.0. If no qualified download is offered, request the
intended pilot artifact rather than substituting an unverified one.

The course was recorded from a Linux source checkout. It does not certify a clean-machine Windows
installer, AppImage, signing status or every training environment. Proprietary usage permission remains
required even though current alpha licence enforcement is unrestricted.

## Windows

1. Obtain the 64-bit Windows installer and its matching manifest/checksum from the approved source.
2. Verify the file, then follow its per-user installation flow. Launch **Granum** from the Start menu.
3. Confirm the dashboard and service open and report the intended build and project root.

Use the operating-system compatibility stated for that particular artifact. If Windows shows a
security warning or an unexpected publisher, stop and verify with the maintainer. Do not bypass
SmartScreen simply to follow a tutorial. A browser fallback and a native window are different
presentation modes; qualify the one your pilot will use.

## Linux

Obtain and verify the x86-64 AppImage for your Linux distribution. Replace the example version in the
commands below with the **one exact verified file**, rather than executing every matching download:

```bash
chmod +x Granum-0.1.0-x86_64.AppImage
./Granum-0.1.0-x86_64.AppImage
```

The Linux installation flow can register an application-menu entry and a user service, and place the
installed app under `~/.local/share/granum`. Inspect the resulting status before deleting your verified
download; retain the previous artifact if you need an upgrade rollback.

Use a supported 64-bit desktop distribution qualified for the artifact. If an AppImage reports a FUSE
problem, check its platform instructions; an extract-and-run mode may be available. Do not install
unrelated system packages or run the application as root merely to suppress the error.

!!! note "The window and the browser"
  `granum open --browser` deliberately opens the dashboard in a browser. The default local address
  is `http://127.0.0.1:8000`; a configured port may differ. A browser and the desktop window can use
  different profiles, so an unsaved recovery draft in one is not necessarily available in the other.

## Training support

Core import, browsing, review and versioning can operate on local files without training support.

Training support can download several gigabytes of PyTorch/CUDA and model-family packages into the
application's add-on environment. **Train model** offers **Install training support** when required.
Model weights, package/version checks and configured third-party integrations may also use the network;
dependency installation is not the only possible connection.

CUDA training needs a compatible NVIDIA driver and runtime. CPU training can be slow; the course
includes a no-GPU route using recorded evidence. Read the detected device and installation/training
logs instead of assuming that an installed add-on means a model successfully ran.

## Where your work is kept

Confirmed saves write project records to disk. **Unsaved edits are browser drafts**, subject to storage
acknowledgement, profile/origin and quota limits. Linked source images may live outside the project root.

| What | Where |
|---|---|
| Projects: datasets, versions, reviews, comments, dataset versions, runs and their metrics | `~/granum` |
| Model weights, trained and downloaded | `~/granum-training` |
| Settings | `~/.config/granum/config.granum.yaml` |
| Service log | `~/.local/state/granum/service.log` |
| Desktop-window profile: preferences and recovery storage | `~/.local/share/granum/window` |

These are common Linux defaults, not a universal location for all installs. Windows uses user-profile,
AppData and LocalAppData folders; an ordinary browser manages its own profile. Confirm your actual roots
with the CLI and [Files and settings](/docs/reference/files).

To keep projects elsewhere, configure the intended project root before creating work. For a portable
backup, stop writers and use [backup/restore](/docs/course/backup). Merely copying the project directory
can omit externally referenced images and weights.

## Check the install

```bash
granum app status      # service, port, project root, version
granum version
granum build-info      # build identity and provenance; inspect the actual artifact
```

Where the Linux installer registered a systemd user unit, `systemctl --user status granum` reports it;
`restart` and `stop` manage that service. Do not stop it during active writes or model jobs without
understanding their outcome. On a foreground development service, inspect its terminal instead.

## Upgrade and uninstall

Before upgrading, retain the previous artifact and rehearse a restore in a separate root. Verify the
new build on your intended platform rather than replacing the only working copy without a rollback.

Use the platform's installation/uninstallation flow: Windows **Settings → Apps**, or the Linux app's
`app uninstall` command where supported. Project-data retention is not a backup guarantee. Inspect
what the particular installer removes, and never delete project/media folders just to repair a launcher.

Authorized developers can use the repository's installation and development instructions. Source builds
and development environments are distinct from qualified customer artifacts.

Next: [prepare the real sample](/docs/course/setup).
