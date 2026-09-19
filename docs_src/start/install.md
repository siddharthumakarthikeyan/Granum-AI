---
title: Install Granum
summary: One download per platform, no dependencies to manage, and everything kept in folders you can back up.
---

Granum is a desktop application with a background service. The download contains everything it needs —
Python, the libraries, the dashboard and its own window — so there is nothing to install alongside it and
no internet connection required after the download.

## Windows

1. Download the installer from the [download page](/download).
2. Run it. It installs for your user only — no administrator rights needed — adds **Granum** to the
   Start menu, and starts the background service.
3. Launch **Granum**. The app opens in its own window.

Windows 10 and 11, 64-bit. If Windows shows *Windows protected your PC*, choose **More info → Run
anyway**: the build is not yet signed with a commercial certificate, so SmartScreen has no reputation
for it.

## Linux

Download `Granum-<version>-x86_64.AppImage`, then:

```bash
chmod +x Granum-*-x86_64.AppImage
./Granum-*-x86_64.AppImage
```

On first launch Granum copies itself to `~/.local/share/granum/Granum.AppImage` (you can delete the
download), adds itself to the application menu, sets up a service that starts at login, and opens its
window.

Requirements: 64-bit Linux from about 2020 onward — Ubuntu 22.04, Debian 12, Fedora 36 or newer — with a
desktop. If the file fails with a FUSE error, run it once with `--appimage-extract-and-run`, or install
`fuse3`.

!!! note "The window and the browser"
    Granum's window uses WebKitGTK, which most desktops already have. If it is missing, install it with
    `sudo apt install python3-gi gir1.2-webkit2-4.1`; until then Granum opens in your browser instead.
    Either way the dashboard is available at `http://127.0.0.1:8000`, and `granum open --browser` opens
    it there deliberately.

## Training support

Importing, browsing, reviewing, editing and versioning work from the first launch, offline.

Training needs PyTorch, which is roughly 3 GB with CUDA, so it is not in the download. The first time you
open **Train model**, Granum offers **Install training support** and downloads it into
`~/.local/share/granum/addons` — never into your system Python. This is the only step that needs the
internet.

GPU training needs an NVIDIA driver on the machine. Without a GPU, training still runs on the CPU; expect
it to be slow enough that you will want a small model and a small dataset.

## Where your work is kept

Everything is written to disk as you do it, not held in the browser. Closing the window, logging out,
rebooting, upgrading or reinstalling keeps all of it.

| What | Where |
|---|---|
| Projects: datasets, versions, reviews, comments, dataset versions, runs and their metrics | `~/granum` |
| Model weights, trained and downloaded | `~/granum-training` |
| Settings | `~/.config/granum/config.granum.yaml` |
| Service log | `~/.local/state/granum/service.log` |
| Window storage: your reviewer name, unsaved-edit recovery | `~/.local/share/granum/window` |

To keep projects elsewhere, run `granum config project-root /path/to/granum` before installing. To back
up, copy `~/granum` and `~/granum-training`. See [Files and settings](/docs/reference/files) for the
layout inside those folders.

## Check the install

```bash
granum app status      # service, port, project root, version
granum version
```

On Linux the service is a systemd user unit: `systemctl --user status granum` (also `restart`, `stop`).
It starts when you log in. To keep it running while you are logged out, enable lingering once with
`sudo loginctl enable-linger $USER`.

## Upgrade and uninstall

- **Windows**: run the newer Setup.exe; it replaces the installed version. Uninstall from
  **Settings → Apps**. Your data is kept.
- **Linux**: open the newer AppImage once; it replaces the installed copy and restarts the service.
  Uninstall with `~/.local/share/granum/Granum.AppImage app uninstall`. Your data is kept.
- **From source**: `git pull && ./install.sh` to upgrade, `./install.sh --uninstall` to remove.

Uninstalling never touches `~/granum` or `~/granum-training`. Delete those folders yourself if you mean
to remove the data too.
