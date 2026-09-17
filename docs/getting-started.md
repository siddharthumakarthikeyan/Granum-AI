# Getting started

This guide takes a COCO detection dataset from a folder on disk to a trained model.

## 1. Install

### The app (recommended)

Download `Granum-<version>-x86_64.AppImage`, then:

```bash
chmod +x Granum-*-x86_64.AppImage
./Granum-*-x86_64.AppImage
```

This one file contains everything Granum needs: Python, all libraries, the dashboard and a Chromium-based
window. It works without an internet connection and without installing anything on the system.

On first launch Granum:

- copies itself to `~/.local/share/granum/Granum.AppImage` (the download can then be deleted);
- adds **Granum** to the application menu;
- sets up a background service that starts at login;
- opens its window.

Requirements: 64-bit Linux from about 2020 onwards (Ubuntu 22.04, Debian 12, Fedora 36 or newer) with a
desktop. If the file does not start with a FUSE error, run it once with
`./Granum-*-x86_64.AppImage --appimage-extract-and-run`, or install `fuse3`.

### Training support

Importing, reviewing, editing and shipping work offline from the first launch. Training needs PyTorch,
which is large (about 3 GB with CUDA), so it is not in the download. The first time you open
**Train model**, Granum offers **Install training support**: it downloads PyTorch and Ultralytics into
`~/.local/share/granum/addons`, never into the system. This is the only step that needs the internet.
GPU training needs the NVIDIA driver installed on the machine.

### From source

For development, or on machines where you prefer a Python install:

```bash
git clone <your-remote>/granum.git
cd granum
./install.sh --training       # omit --training if you will not train from the dashboard
```

The installer builds the dashboard and installs Granum into `~/.local/share/granum/venv` with the same
menu entry and background service.

Check either install with:

```bash
granum app status             # or: ~/.local/share/granum/Granum.AppImage app status
```

### Your work is kept

Everything you do is written to disk as you do it, not held in the browser. Closing the browser,
logging out, rebooting, reinstalling or upgrading keeps all of it:

| What | Where |
|---|---|
| Projects, dataset versions, box edits, reviews, comments, shipments, training runs | `~/granum` |
| Model weights, trained and downloaded | `~/granum-training` |
| Settings | `~/.config/granum/config.granum.yaml` |
| Service log | `~/.local/state/granum/service.log` |

The reviewer name you type in the Review tab is remembered by the browser.

To keep projects elsewhere, run `granum config project-root /path/to/granum` before installing.
To back up, copy `~/granum` and `~/granum-training`.

### Upgrade and uninstall

- **App**: open the newer AppImage once; it replaces the installed copy and restarts the service.
  Uninstall with `~/.local/share/granum/Granum.AppImage app uninstall`. Data is kept.
- **From source**: `git pull && ./install.sh` to upgrade, `./install.sh --uninstall` to remove. Data is kept.

## 2. Open the dashboard

Open **Granum** from the application menu, or run `granum open`. Granum opens in its own window, a
standalone app with no browser tabs or address bar, and starts the service first if it is not running.
Closing the window leaves the service running, so the next launch is instant.

The dashboard is also available in any browser at http://127.0.0.1:8000 (`granum open --browser`).
The window needs WebKitGTK, which Ubuntu desktops include; if it is missing, install it with
`sudo apt install python3-gi gir1.2-webkit2-4.1`, and until then Granum opens in the browser. The service runs on your machine only, and your images
are never uploaded.

## 3. Import a dataset

Granum expects COCO annotation files, one per set, for example as exported by Roboflow:

```
human_aerial/
├── train/  _annotations.coco.json  + images
├── valid/  _annotations.coco.json  + images
└── test/   _annotations.coco.json  + images
```

1. Click **Import data** in the sidebar.
2. Open the dataset folder, or any one of its set folders. All sets are found together.
3. Leave all sets ticked and click **Add all sets**.
4. Choose how thoroughly to check images (*All images* is the safest) and click **Run preflight**.
5. Read the findings. Each has counts per set, example images and a recommended option. Change any
   option you disagree with.
6. Enter a project name and click **Import**.

Nothing is written until step 6. See [Importing data](importing.md) for every check.

## 4. Review

1. Open **Review** in the sidebar and type your name in the *Reviewer* box.
2. Click an image. Check its boxes, then press `A` to mark it *Reviewed* and move to the next one,
   or write what is wrong and press `R` to send it for *Rework*.
3. Fix boxes directly: drag to draw, click a box to select it, `Delete` to remove it.
4. Use the checkboxes and the bottom bar to act on many images at once.

Details and shortcuts: [Review and shipping](review-and-shipping.md).

## 5. Ship

When every image is reviewed, the **Ship** button in the Review header becomes available. Click
it, add an optional note, and ship. The shipment records the exact version of every set.

Images you cannot resolve yet can be **isolated** first. They are set aside, the rest ships, and
you return them later.

## 6. Train

1. Open **Runs** and click **Train model**.
2. The *Train* and *Validation* lists show shipped versions only. The newest are preselected.
3. Choose a model family (YOLO, RT-DETR or RF-DETR), weights, image size and epochs.
4. Optionally compare with an earlier run. Both are scored on the same current validation labels.
5. Click **Start training** and follow progress on the Runs page.

## 7. Inspect and improve

- Open the run for mAP50, precision and recall per epoch.
- Open **Samples** to see when each image was learned: *early*, *mid*, *late*, *forgotten* or *never*.
  Images that are never learned are often label errors.
- Click an image to step through its predictions round by round.
- Fix what you find in Review, ship the new version, and train again.

## Without the dashboard

Everything above is also available from Python and the CLI:

```bash
granum import coco train=human_aerial/train/_annotations.coco.json \
                   valid=human_aerial/valid/_annotations.coco.json --project aerial
python examples/08_aerial_pipeline.py --project-root ~/granum --data ~/datasets/human_aerial
```

See [Python SDK](python-sdk.md).
