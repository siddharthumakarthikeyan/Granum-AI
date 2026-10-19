"""A cancellable, isolated SAM worker; proposals never change the source dataset."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--table", required=True)
    parser.add_argument("--row", required=True, type=int)
    parser.add_argument("--model", required=True)
    parser.add_argument("--prompts", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)

    import granum
    from granum.core.augment import load_image
    from granum.core.prelabel import box_column
    from granum.formats._common import image_column
    from granum.integration.sam import propose_mask

    granum.set_config(granum.Config.load(overrides={"project-root-url": args.project_root}, use_config_files=False, use_env=False))
    table = granum.Table.from_url(args.table)
    record = table.to_arrow().slice(args.row, 1).to_pylist()[0]
    geometry = record.get(box_column(table)) or {}
    image = load_image(record[image_column(table)], int(geometry.get("width") or 0), int(geometry.get("height") or 0))
    print("GRANUM_PHASE Loading SAM and proposing a mask", flush=True)
    result = propose_mask(image, model=args.model, **json.loads(args.prompts))
    target = Path(args.output)
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps(result))
    temporary.replace(target)
    print("GRANUM_PROGRESS 1 1", flush=True)
    print('GRANUM_RESULT {"proposed": true}', flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
