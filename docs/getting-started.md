# Getting started

This guide takes a COCO detection dataset from a folder on disk to a trained model.

## 1. Install

Requirements: Python 3.10 or newer, Node.js 20 or newer, and for training an NVIDIA GPU with PyTorch.

```bash
git clone <your-remote>/granum.git
cd granum

cd web && npm ci && npm run build && cd ..        # build the dashboard into the package
python -m venv .venv && source .venv/bin/activate
pip install -e ".[service,images,pandas]"

pip install ultralytics      # optional: YOLO and RT-DETR training
pip install rfdetr           # optional: RF-DETR training
```

Check the install:

```bash
granum version
granum config show           # where projects are stored and which folders may be imported
```

By default projects live in `~/granum` and datasets may be imported from anywhere under your home
folder. Change either with flags, environment variables or a config file. See [Service and CLI](service.md).

## 2. Start the dashboard

```bash
granum service --open        # http://127.0.0.1:8000
```

The service runs on your machine only. Your images are never uploaded.

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
