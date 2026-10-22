"""Classification and semantic training with explicit splits and canonical metrics."""
from __future__ import annotations

import os
import random
import time
from pathlib import Path
from typing import Any

import fsspec
import numpy as np

from granum.core.objects.table import WEIGHT_COLUMN
from granum.errors import GranumError
from granum.formats._common import kept_rows
from granum.formats.semantic import semantic_pixels
from granum.training.data import classification_label, contract


def build_model(version: str, classes: int, *, pretrained: bool = True) -> Any:
    import torch
    from torchvision import models

    if version == "resnet18":
        model = models.resnet18(weights=models.ResNet18_Weights.DEFAULT if pretrained else None)
        model.fc = torch.nn.Linear(model.fc.in_features, classes)
        return model
    if version == "lraspp-mobilenet-v3":
        return models.segmentation.lraspp_mobilenet_v3_large(
            weights=None, num_classes=classes,
            weights_backbone=models.MobileNet_V3_Large_Weights.IMAGENET1K_V1 if pretrained else None,
        )
    raise GranumError(f"Unknown torchvision model: {version}")


def image_tensor(path: str, size: int) -> Any:
    from PIL import Image
    from torchvision.transforms import functional as F

    from granum.core.url import Url

    with fsspec.open(Url(path).resolved, "rb") as stream, Image.open(stream) as image:
        image = image.convert("RGB").resize((size, size), Image.Resampling.BILINEAR)
        return F.normalize(F.to_tensor(image), [.485, .456, .406], [.229, .224, .225])


class ImageDataset:
    def __init__(self, table: Any, task: str, size: int, *, training: bool = False) -> None:
        self.rows = table.to_arrow().to_pylist()
        self.spec, self.task, self.size = contract(table, task), task, size
        self.indices = kept_rows(table, 0) if training else list(range(len(self.rows)))
        self.class_indices = {label: i for i, label in enumerate(self.spec["classes"])}

    def __len__(self) -> int:
        return len(self.indices)

    def __getitem__(self, offset: int) -> tuple[Any, Any, int]:
        import torch
        from PIL import Image

        index = self.indices[offset]
        row = self.rows[index]
        image = image_tensor(row[self.spec["image"]], self.size)
        if self.task == "classify":
            target = self.class_indices[classification_label(row, self.spec)]
        else:
            pixels = semantic_pixels(row[self.spec["column"]], set(self.class_indices), self.spec["ignore_index"])
            pixels = np.asarray(Image.fromarray(pixels).resize((self.size, self.size), Image.Resampling.NEAREST))
            target = np.full(pixels.shape, -100, dtype=np.int64)
            for label, at in self.class_indices.items():
                target[pixels == label] = at
            target = torch.from_numpy(target)
        return image, target, index


def _output(model: Any, images: Any, task: str) -> Any:
    output = model(images)
    return output["out"] if task == "semantic" else output


def _device(requested: str) -> str:
    import torch

    if requested == "auto":
        return "cuda:0" if torch.cuda.is_available() else "cpu"
    if requested.startswith("cuda") and not torch.cuda.is_available():
        raise GranumError("CUDA was requested but is unavailable; install a compatible PyTorch build.")
    return requested


def evaluate(model: Any, table: Any, task: str, *, size: int, device: str, batch: int = 8,
             run: Any = None, split: str = "valid", epoch: int | None = None,
             store_masks: bool = True, workers: int = 0) -> dict[str, float]:
    """Use every evaluation row once; aggregate semantic counts, never image means."""
    import torch
    import torch.nn.functional as F
    from torch.utils.data import DataLoader

    from granum.core.schemas import CategoricalLabelSchema
    from granum.metrics.collectors import ClassificationMetricsCollector
    from granum.metrics.predictor import Prediction
    from granum.metrics.semantic import SemanticMetricsCollector

    dataset = ImageDataset(table, task, size)
    spec = dataset.spec
    classes = spec["classes"]
    value_map = table.schema[spec["column"]].value_map
    collector = (ClassificationMetricsCollector([spec["names"][c] for c in classes]) if task == "classify"
                 else SemanticMetricsCollector(value_map, gt_column=spec["column"], ignore_index=spec["ignore_index"], store_masks=store_masks))
    schemas = collector.column_schemas()
    if task == "classify":
        schemas["predicted"] = CategoricalLabelSchema(value_map=value_map, writable=False)
    values: dict[str, list[Any]] = {"example_id": [], **{key: [] for key in schemas}}
    confusion = np.zeros((len(classes), len(classes)), dtype=np.int64)
    model.eval()
    with torch.inference_mode():
        for images, targets, indices in DataLoader(dataset, batch_size=batch, shuffle=False, num_workers=workers):
            output = _output(model, images.to(device), task)
            if task == "classify":
                logits = output.cpu().numpy()
                metrics = collector.collect({"label": targets.tolist()}, Prediction(logits))
                predicted = logits.argmax(1)
                np.add.at(confusion, (targets.numpy(), predicted), 1)
                metrics["predicted"] = [classes[i] for i in metrics["predicted"]]
            else:
                geometries = [dataset.rows[i][spec["column"]] for i in indices.tolist()]
                maps = []
                for logits, geometry in zip(output, geometries):
                    labels = F.interpolate(logits[None], size=(int(geometry["height"]), int(geometry["width"])),
                                           mode="bilinear", align_corners=False)[0].argmax(0).cpu().numpy()
                    maps.append(np.asarray(classes, dtype=np.int64)[labels])
                metrics = collector.collect({spec["column"]: geometries}, Prediction(maps))
            values["example_id"].extend(indices.tolist())
            for key, entries in metrics.items():
                values[key].extend(entries)
    if task == "classify":
        support, predicted_count = confusion.sum(1), confusion.sum(0)
        denominator = support + predicted_count
        f1 = np.divide(2 * confusion.diagonal(), denominator, out=np.zeros(len(classes)), where=denominator > 0)
        scores = {"accuracy": float(np.mean(values["accuracy"])), "loss": float(np.mean(values["loss"])),
                  "macro_f1": float(f1[denominator > 0].mean()), "images": len(dataset)}
    else:
        intersections = np.array([sum(values[f"class_{c}_intersection"]) for c in classes], dtype=np.float64)
        unions = np.array([sum(values[f"class_{c}_union"]) for c in classes], dtype=np.float64)
        pixels = sum(values["pixel_count"])
        if pixels <= 0:
            raise GranumError("No labelled evaluation pixels remain.")
        scores = {"mean_iou": float((intersections[unions > 0] / unions[unions > 0]).mean()),
                  "pixel_accuracy": sum(values["pixel_correct"]) / pixels, "images": len(dataset),
                  **{f"class_{c}_iou": float(i / u) for c, i, u in zip(classes, intersections, unions) if u > 0}}
    if run is not None:
        run.add_metrics(values, schema=schemas, foreign_table_url=table.url,
                        constants={"split": split, **({"epoch": epoch} if epoch is not None else {})})
    return scores


def train_vision(args: Any, train: Any, valid: Any, work: Path) -> tuple[Any, Path]:
    os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")
    import torch
    from torch.utils.data import DataLoader, WeightedRandomSampler

    import granum
    from granum.training.models import task_for_version
    from granum.training.train import phase, progress, run_parameters, step

    seed = getattr(args, "seed", 0)
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.set_num_threads(min(4, os.cpu_count() or 1))
    torch.use_deterministic_algorithms(True, warn_only=True)
    task = task_for_version(args.version)
    device = _device(getattr(args, "device", "auto"))
    batch = args.batch or (16 if task == "classify" else 8)
    workers = getattr(args, "workers", 2)
    dataset = ImageDataset(train, task, args.imgsz, training=True)
    pretrained = not getattr(args, "no_pretrained", False)
    phase("Loading the model")
    model = build_model(args.version, len(dataset.spec["classes"]), pretrained=pretrained).to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=getattr(args, "learning_rate", .0003), weight_decay=.0001)
    generator = torch.Generator().manual_seed(seed)
    weights = [float(dataset.rows[i].get(WEIGHT_COLUMN, 1)) for i in dataset.indices]
    sampler = WeightedRandomSampler(weights, len(weights), replacement=True, generator=generator) if len(set(weights)) > 1 else None
    loader = DataLoader(dataset, batch_size=batch, shuffle=sampler is None, sampler=sampler,
                        num_workers=workers, generator=generator, pin_memory=device.startswith("cuda"))
    output = work / "runs" / args.run_name / "weights"
    output.mkdir(parents=True, exist_ok=False)
    best = output / "best.pt"
    run = granum.init(args.project, args.run_name, parameters={**run_parameters(args, train, valid),
        "device": device, "pretrained": pretrained, "learning_rate": optimizer.param_groups[0]["lr"],
        "seed": seed, "class_names": dataset.spec["names"], "batch": batch,
        "preflight": getattr(args, "preflight", {}), "torch_version": str(torch.__version__)})
    started, best_score = time.monotonic(), -float("inf")
    if device.startswith("cuda"):
        torch.cuda.reset_peak_memory_stats()
    try:
        for epoch in range(args.epochs):
            phase(f"Training, round {epoch + 1} of {args.epochs}")
            model.train()
            loss_sum = samples = 0
            for iteration, (images, targets, _) in enumerate(loader):
                images, targets = images.to(device), targets.to(device)
                optimizer.zero_grad(set_to_none=True)
                logits = _output(model, images, task)
                if task == "semantic" and not (targets != -100).any():
                    raise GranumError("Resizing removed all labelled pixels; increase the image size.")
                loss = torch.nn.functional.cross_entropy(logits, targets, ignore_index=-100)
                if not torch.isfinite(loss):
                    raise GranumError("Training produced a nonfinite loss.")
                loss.backward()
                optimizer.step()
                loss_sum += loss.item() * len(images)
                samples += len(images)
                step(iteration + 1, len(loader))
            phase(f"Validating round {epoch + 1}")
            collect = args.track_learning or epoch + 1 == args.epochs
            scores = evaluate(model, valid, task, size=args.imgsz, device=device, batch=batch, workers=workers,
                              run=run if collect else None, split="valid", epoch=epoch)
            granum.log({"epoch": epoch, "train_loss": loss_sum / samples, **{k: v for k, v in scores.items() if k != "images"}}, run=run)
            score = scores["accuracy" if task == "classify" else "mean_iou"]
            if score > best_score:
                best_score = score
                payload = {"format": 1, "version": args.version, "task": task, "classes": dataset.spec["classes"],
                           "names": dataset.spec["names"], "ignore_index": dataset.spec["ignore_index"],
                           "size": args.imgsz, "epoch": epoch, "state_dict": model.state_dict()}
                temporary = best.with_suffix(".tmp")
                torch.save(payload, temporary)
                temporary.replace(best)
                run.set_parameters({"best_epoch": epoch + 1, "weights": str(best)})
            if collect:
                phase(f"Recording training images, round {epoch + 1}")
                evaluate(model, train, task, size=args.imgsz, device=device, batch=batch, workers=workers,
                         run=run, split="train", epoch=epoch)
            progress(epoch + 1, args.epochs)
        run.set_parameters({"training_seconds": time.monotonic() - started,
                            "peak_cuda_bytes": torch.cuda.max_memory_allocated() if device.startswith("cuda") else 0})
        return run, best
    except BaseException:
        run.set_status("failed")
        raise


def score_checkpoint(weights: Path, table: Any, *, device: str = "auto", run: Any = None,
                     split: str = "test", workers: int = 0) -> dict[str, float]:
    import torch

    checkpoint = torch.load(weights, map_location="cpu", weights_only=True)
    spec = contract(table, checkpoint["task"])
    if spec["names"] != checkpoint["names"] or spec["ignore_index"] != checkpoint["ignore_index"]:
        raise GranumError("Model and evaluation table class contracts differ.")
    model = build_model(checkpoint["version"], len(checkpoint["classes"]), pretrained=False)
    model.load_state_dict(checkpoint["state_dict"])
    chosen = _device(device)
    model.to(chosen)
    return evaluate(model, table, checkpoint["task"], size=checkpoint["size"], device=chosen,
                    run=run, split=split, workers=workers)
