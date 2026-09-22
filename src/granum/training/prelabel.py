"""Draft a set's labels with a model, so labelling becomes correcting.

What the dashboard's *Pre-label* button runs, in its own process for the same reason
training and checking are: it is a pass over every image with a detector on the GPU.
Usable directly:

    python -m granum.training.prelabel --project-root ROOT --project aerial \\
        --table URL --weights /path/best.pt --mode empty --conf 0.4

It writes a new version of each set it is given, with the model's boxes added as labels and
every box marked with where it came from (see :mod:`granum.core.prelabel`). Nothing is
overwritten: the previous version keeps whatever was there, and in the default ``empty``
mode an image that already has labels is not touched at all.

Progress is reported as ``GRANUM_PHASE`` and ``GRANUM_PROGRESS`` lines, and what was written
as one ``GRANUM_RESULT <json>`` line, which the service reads back when the process ends.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

#: Predictions below this are not worth a person's time to delete.
PRELABEL_CONFIDENCE = 0.4

#: Images handed to the model at once.
BATCH = 16


def phase(text: str) -> None:
    print(f"GRANUM_PHASE {text}", flush=True)


def progress(done: int, total: int) -> None:
    print(f"GRANUM_PROGRESS {min(done, total)} {total}", flush=True)


def predictions_for(
    table: Any,
    predictor: Any,
    *,
    column: str,
    confidence: float,
    batch: int,
    on_progress: Any = None,
) -> dict[int, dict[str, Any]]:
    """Every image of ``table`` read once: row -> the boxes the model would draw there.

    The image's own size comes from the model's view of it, because an unlabelled set has
    no geometry to read it from -- which is the whole case this exists for.
    """
    from PIL import Image

    from granum.core.url import Url

    arrow = table.to_arrow()
    images = arrow.column("image").to_pylist()
    sizes = arrow.column(column).to_pylist() if column in table.columns else [None] * len(images)
    out: dict[int, dict[str, Any]] = {}
    for start in range(0, len(images), batch):
        rows = list(range(start, min(start + batch, len(images))))
        answers = predictor({"image": [images[row] for row in rows]})
        for row, answer in zip(rows, answers):
            known = sizes[row] or {}
            width, height = float(known.get("width") or 0), float(known.get("height") or 0)
            if not width or not height:
                with Image.open(Url(images[row]).resolved) as handle:
                    width, height = float(handle.width), float(handle.height)
            instances = [
                {"vertices": [float(v) for v in box], "label": int(label), "confidence": float(score)}
                for box, score, label in zip(answer["boxes"], answer["scores"], answer["labels"])
                if float(score) >= confidence
            ]
            out[row] = {"width": width, "height": height, "instances": instances}
        if on_progress is not None:
            on_progress(rows[-1] + 1, len(images))
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--project", required=True)
    parser.add_argument("--table", dest="tables", action="append", required=True,
                        help="a set's newest version, repeatable")
    parser.add_argument("--weights", default=None, help="a trained model's weights file")
    parser.add_argument("--pretrained", default=None, help="a model that has not seen this data")
    parser.add_argument("--from-run", default=None, help="the run the weights came from, for the record")
    parser.add_argument("--mode", choices=["empty", "replace"], default="empty")
    parser.add_argument("--conf", type=float, default=PRELABEL_CONFIDENCE)
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--batch", type=int, default=BATCH)
    args = parser.parse_args(argv)
    if bool(args.weights) == bool(args.pretrained):
        parser.error("pass exactly one of --weights (a model you trained) and --pretrained")
    if args.weights and not Path(args.weights).exists():
        print(f"no weights at {args.weights}", file=sys.stderr)
        return 1

    import granum
    from granum import Table
    from granum.core.prelabel import box_column, write_prelabelled
    from granum.integration.ultralytics import YOLOPredictor

    granum.set_config(granum.Config.load(overrides={"project-root-url": str(args.project_root)},
                                         use_config_files=False, use_env=False))
    source = args.weights or args.pretrained
    tables = [Table.from_url(url) for url in args.tables]
    total = sum(len(table) for table in tables)
    done = 0
    written = []

    phase("Loading the model")
    for table in tables:
        column = box_column(table)
        value_map = table.schema[column].value_map or {}
        predictor = YOLOPredictor(source, value_map, conf=args.conf, imgsz=args.imgsz,
                                  on_unknown="drop" if args.pretrained else "raise")
        phase(f"Drawing boxes on the {table.base_name} set")
        at = done
        result = write_prelabelled(
            table,
            predictions_for(table, predictor, column=column, confidence=args.conf, batch=args.batch,
                            on_progress=lambda seen, _n, at=at: progress(at + seen, total)),
            model=Path(str(source)).name,
            mode=args.mode,
            confidence=args.conf,
        )
        done += len(table)
        progress(done, total)
        written.append({
            "set": table.base_name,
            "from": str(table.url),
            "url": result["url"],
            "name": result["name"],
            "images": result["images"],
            "boxes": result["boxes"],
            "kept": result["kept"],
            #: Classes of this set the model could not speak about, so nothing was drafted
            #: for them. Empty when the model was trained on this data.
            "unknown": predictor.unknown[:20],
        })
        print(f"{table.base_name}: {result['boxes']} boxes on {result['images']} images "
              f"-> {result['name']}", flush=True)

    print("GRANUM_RESULT " + json.dumps({
        "model": Path(str(source)).name,
        "from_run": args.from_run,
        "mode": args.mode,
        "confidence": args.conf,
        "sets": written,
    }), flush=True)
    phase("Finished")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
