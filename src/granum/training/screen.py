"""Run a model once over a dataset's labels, so Findings works without training first.

What the dashboard's *Check the labels* button runs, as a separate process for the same
reason training is: a pass over twelve thousand images is a GPU job, and the service must
stay answerable while it happens. Usable directly:

    python -m granum.training.screen --project-root ROOT --project aerial \\
        --set train=URL --set valid=URL --run-name check-0921 --weights /path/best.pt

The model comes from one of two places, and which one it was is recorded on the run:

``--weights PATH``   a model the user already trained, usually the best run in the project.
                     It knows this dataset's classes exactly, and screening its *current*
                     labels costs one pass rather than another afternoon of training.
``--pretrained``     a detector that has never seen this data. It knows the classes it was
                     trained on, which for a COCO model overlaps some datasets and not
                     others; the overlap is computed and recorded, and the findings are
                     limited to it (see ``granum.metrics.findings.pass_findings``).

The output is an ordinary Granum run with one round of per-image metrics per set -- the same
shape a training run records -- so the findings rules, the review queue and the dashboard
read it without knowing it came from here. It is marked ``kind: screening`` and carries no
scores of its own: nothing was trained, and a number from a model on its own training labels
would only be read as one.

Progress is reported as ``GRANUM_PHASE <text>`` and ``GRANUM_PROGRESS <done> <total>`` lines
on stdout, as the trainer does.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

#: Predictions below this are not worth storing: the rules ignore them, and a pass over a
#: large set writes one row per image with every box it kept.
SCREEN_CONFIDENCE = 0.25


def phase(text: str) -> None:
    print(f"GRANUM_PHASE {text}", flush=True)


def progress(done: int, total: int) -> None:
    print(f"GRANUM_PROGRESS {min(done, total)} {total}", flush=True)


def parse_set(value: str) -> tuple[str, str]:
    """``name=url``: the set's name, and the table version to read it from."""
    name, _, url = value.partition("=")
    if not name or not url:
        raise argparse.ArgumentTypeError(f"--set takes name=url, not {value!r}")
    return name, url


def screen_table(
    model: Any,
    table: Any,
    *,
    run: Any,
    split: str,
    imgsz: int,
    conf: float,
    batch: int,
    tolerant: bool,
) -> dict[str, Any]:
    """One pass over one set, written to ``run`` as a single round of per-image metrics."""
    from granum.core.schemas.geometry import BoundingBoxes2DSchema
    from granum.integration.ultralytics import YOLOPredictor, collect_detection_metrics

    column = next(n for n in table.columns if isinstance(table.schema[n], BoundingBoxes2DSchema))
    value_map = table.schema[column].value_map or {}
    predictor = YOLOPredictor(model, value_map, conf=conf, imgsz=imgsz,
                              on_unknown="drop" if tolerant else "raise")
    collect_detection_metrics(
        model, table, run=run, gt_column=column, epoch=0, split=split,
        conf=conf, imgsz=imgsz, batch_size=batch, store_boxes=True, predictor=predictor,
    )
    return {
        "split": split,
        "table": str(table.url),
        "images": len(table),
        #: The dataset's own class ids this model can speak about, so the rules can leave
        #: the rest alone rather than report them as labels it failed to find.
        "known": sorted(predictor.known),
        "unknown": predictor.unknown[:20],
        "classes": len(value_map),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--project", required=True)
    parser.add_argument("--run-name", required=True)
    parser.add_argument("--set", dest="sets", action="append", required=True, type=parse_set,
                        help="name=url, repeatable: the sets to read, as dataset versions")
    parser.add_argument("--weights", default=None, help="a trained model's weights file")
    parser.add_argument("--pretrained", default=None,
                        help="a model that has not seen this data, e.g. yolo26m.pt")
    parser.add_argument("--from-run", default=None, help="the run the weights came from, for the record")
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--conf", type=float, default=SCREEN_CONFIDENCE)
    parser.add_argument("--batch", type=int, default=16)
    args = parser.parse_args(argv)
    if bool(args.weights) == bool(args.pretrained):
        parser.error("pass exactly one of --weights (a model you trained) and --pretrained")

    import granum
    from granum import Table
    from granum.metrics.findings import RULES_VERSION

    root = Path(args.project_root)
    granum.set_config(granum.Config.load(overrides={"project-root-url": str(root)},
                                         use_config_files=False, use_env=False))
    tables = [(name, Table.from_url(url)) for name, url in args.sets]
    total = sum(len(table) for _, table in tables)

    phase("Loading the model")
    source = args.weights or args.pretrained
    if args.weights and not Path(args.weights).exists():
        print(f"no weights at {args.weights}", file=sys.stderr)
        return 1

    run = granum.init(args.project, args.run_name, parameters={
        # Not a training run, and the dashboard says so rather than showing a run with no
        # scores: nothing was trained, and no number here is a measurement of a model.
        "kind": "screening",
        "framework": "yolo",
        "version": Path(str(source)).name if args.weights else str(source),
        "weights": str(args.weights) if args.weights else None,
        "screened_with": "trained" if args.weights else "pretrained",
        "screened_from_run": args.from_run,
        "imgsz": args.imgsz,
        "confidence": args.conf,
        "rules": RULES_VERSION,
        # The findings rules read one round per set, and everything downstream reads this
        # flag to know there are per-image boxes to judge at all.
        "tracks_learning": True,
        "sets": {name: str(table.url) for name, table in tables},
    })

    done = 0
    covered = []
    for name, table in tables:
        phase(f"Reading the {name} set with the model")
        progress(done, total)
        covered.append(screen_table(source, table, run=run, split=name, imgsz=args.imgsz,
                                    conf=args.conf, batch=args.batch, tolerant=bool(args.pretrained)))
        done += len(table)
        progress(done, total)

    known = sorted({label for entry in covered for label in entry["known"]})
    run.set_parameters({
        "screened": covered,
        # One list for the whole screening: the rules ask it what this model may judge.
        "known_classes": known,
        "covers_all_classes": all(len(entry["known"]) == entry["classes"] for entry in covered),
    })
    run.set_status("finished")
    print(f"screened {total} images in {len(tables)} set(s) with {Path(str(source)).name}", flush=True)
    phase("Finished")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
