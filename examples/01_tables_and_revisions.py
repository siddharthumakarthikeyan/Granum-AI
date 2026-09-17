"""Stage 1 example: build a Table, revise it, and read a specific revision back.

Run it:  python examples/01_tables_and_revisions.py

This is the Stage 1 client test from the build plan, minus a real dataset: create a
Table from an image folder, hand it to a training loop as a Dataset, make three
revisions, show the lineage, then reopen an earlier revision by URL.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import granum
from granum import Table, TableWriter
from granum.schemas import CategoricalLabelSchema, ImageSchema


def build_fake_image_folder(root: Path) -> Path:
    for label, count in [("cat", 4), ("dog", 3)]:
        (root / label).mkdir(parents=True, exist_ok=True)
        for i in range(count):
            (root / label / f"{label}_{i}.jpg").write_bytes(b"\xff\xd8\xff\xe0stub")
    return root


def to_tensors(sample: dict) -> dict:
    """A model-facing transform. Module-level so it stays picklable for DataLoader."""
    return {"path": sample["image"], "target": sample["label"]}


def main() -> None:
    workdir = Path(tempfile.mkdtemp(prefix="granum-example-"))
    granum.set_config(
        granum.Config.load(
            overrides={"project-root-url": str(workdir / "granum")},
            use_config_files=False,
            use_env=False,
        )
    )
    images = build_fake_image_folder(workdir / "pets")

    print("== 1. import ==")
    table = Table.from_image_folder(images, project_name="pets-demo", table_name="initial")
    print(f"   {table}")
    print(f"   classes: {table.get_simple_value_map('label')}")
    print(f"   sample 0: {table[0]}")

    print("\n== 2. use it as a Dataset ==")
    view = table.with_transform(to_tensors)
    print(f"   len(view)={len(view)}  view[0]={view[0]}")

    print("\n== 3. three revisions ==")
    corrected = table.set_values("label", {0: 1})          # fix a wrong label
    trimmed = corrected.delete_rows([6])                   # drop an unusable image
    curated = trimmed.set_weights({0: 0.0, 1: 2.0})        # down- and up-weight
    print(f"   corrected -> {corrected.name}")
    print(f"   trimmed   -> {trimmed.name} ({len(trimmed)} rows)")
    print(f"   curated   -> {curated.name}")

    print("\n== 4. lineage ==")
    for depth, revision in enumerate(curated.lineage()):
        op = revision.producer.get("op", "create")
        print(f"   {'  ' * depth}{revision.name}  [{op}]  rows={len(revision)}")

    print("\n== 5. resolve revisions ==")
    print(f"   table.latest() -> {table.latest().name}")
    reopened = Table.from_url(trimmed.url)
    print(f"   reopened {reopened.name}: {len(reopened)} rows, columns {reopened.columns}")

    print("\n== 6. TableWriter for programmatic data ==")
    writer = TableWriter(
        schema={
            "image": ImageSchema(sample_type="url"),
            "label": CategoricalLabelSchema(classes=["cat", "dog"]),
        },
        project_name="pets-demo",
        dataset_name="synthetic",
    )
    for i in range(5):
        writer.add_row({"image": f"/synthetic/{i}.jpg", "label": i % 2})
    synthetic = writer.finalize()
    print(f"   wrote {synthetic.name!r} with {len(synthetic)} rows")

    print(f"\nproject root: {workdir / 'granum'}")


if __name__ == "__main__":
    main()
