"""Models and task contracts available in the training dashboard."""

from __future__ import annotations

import importlib.util
from typing import Any

FAMILIES: list[dict[str, Any]] = [
    {
        "id": "yolo",
        "name": "YOLO",
        "maker": "Ultralytics",
        "package": "ultralytics",
        "summary": "Fast and reliable. The best place to start.",
        "detail": "Trains quickly, runs in real time on modest hardware, and is the most widely used detector.",
        "supports_closer": True,
        "versions": [
            {"id": "yolo26n.pt", "name": "YOLO26 nano", "size": "nano", "note": "Fastest. Good for trying things out."},
            {"id": "yolo26s.pt", "name": "YOLO26 small", "size": "small", "note": "A good balance of speed and accuracy."},
            {"id": "yolo26m.pt", "name": "YOLO26 medium", "size": "medium", "note": "More accurate, about three times slower."},
            {"id": "yolo11n.pt", "name": "YOLO11 nano", "size": "nano", "note": "Previous generation, very well tested."},
            {"id": "yolo11s.pt", "name": "YOLO11 small", "size": "small", "note": "Previous generation, very well tested."},
            {"id": "yolov8n.pt", "name": "YOLOv8 nano", "size": "nano", "note": "Older; use to match an existing YOLOv8 setup."},
        ],
    },
    {
        "id": "rtdetr",
        "name": "RT-DETR",
        "maker": "Baidu, through Ultralytics",
        "package": "ultralytics",
        "summary": "A transformer detector. Often better in crowded scenes.",
        "detail": "Sees the whole image at once, which helps with many overlapping objects. Slower to train and needs more graphics memory.",
        "supports_closer": True,
        "versions": [
            {"id": "rtdetr-l.pt", "name": "RT-DETR large", "size": "large", "note": "Needs about 8 GB of graphics memory at batch 8."},
            {"id": "rtdetr-x.pt", "name": "RT-DETR extra large", "size": "xlarge", "note": "Most accurate, slowest."},
        ],
    },
    {
        "id": "rfdetr",
        "name": "RF-DETR",
        "maker": "Roboflow",
        "package": "rfdetr",
        "summary": "A modern transformer detector that adapts well to new data.",
        "detail": "Built on a large pretrained vision backbone, so it often learns from fewer images. Uses its own input size, so 'look closer' does not apply.",
        "supports_closer": False,
        "versions": [
            {"id": "nano", "name": "RF-DETR nano", "size": "nano", "note": "Fastest RF-DETR."},
            {"id": "small", "name": "RF-DETR small", "size": "small", "note": "A good balance."},
            {"id": "medium", "name": "RF-DETR medium", "size": "medium", "note": "More accurate, slower."},
            {"id": "base", "name": "RF-DETR base", "size": "base", "note": "The original release size."},
            {"id": "large", "name": "RF-DETR large", "size": "large", "note": "Most accurate RF-DETR, needs a large GPU."},
        ],
    },
]

# Task-labelled variants use the same public Ultralytics training API.
FAMILIES.extend([
    {"id": "classifier", "name": "Image classification", "maker": "Torchvision", "package": "torchvision",
     "summary": "One class for each image.", "detail": "Fine-tune an ImageNet-pretrained ResNet-18 on whole-image labels.",
     "supports_closer": True, "image_sizes": [224, 320, 512], "default_image_size": 224,
     "versions": [{"id": "resnet18", "name": "ResNet-18", "size": "small", "task": "classify",
                   "note": "Records per-image loss, confidence and accuracy."}]},
    {"id": "semantic", "name": "Semantic segmentation", "maker": "Torchvision", "package": "torchvision",
     "summary": "One class for each pixel.", "detail": "Fine-tune LR-ASPP with an ImageNet-pretrained MobileNetV3 backbone. Unlabelled pixels are ignored.",
     "supports_closer": True, "image_sizes": [224, 320, 512], "default_image_size": 320,
     "versions": [{"id": "lraspp-mobilenet-v3", "name": "LR-ASPP MobileNetV3", "size": "small", "task": "semantic",
                   "note": "Records pixel accuracy, class IoU and prediction masks."}]},
])

for _task, _suffix, _label in (("segment", "seg", "segmentation"), ("pose", "pose", "keypoints"), ("obb", "obb", "oriented boxes")):
    for _base in ("yolo26n", "yolo26s", "yolo11n", "yolo11s"):
        FAMILIES[0]["versions"].append({"id": f"{_base}-{_suffix}.pt", "name": f"{_base.upper()} · {_label}",
                                       "size": "nano" if _base.endswith("n") else "small", "task": _task,
                                       "note": f"Learns {_label}; requires matching annotations."})


def task_for_version(version: str) -> str:
    return next((str(v.get("task", "detect")) for f in FAMILIES for v in f["versions"] if v["id"] == version), "detect")


def family(family_id: str) -> dict[str, Any]:
    for entry in FAMILIES:
        if entry["id"] == family_id:
            return entry
    raise KeyError(family_id)


def version_ids(family_id: str) -> list[str]:
    return [v["id"] for v in family(family_id)["versions"]]


def catalogue() -> list[dict[str, Any]]:
    """Families with whether their package is installed in this Python."""
    out = []
    for entry in FAMILIES:
        installed = importlib.util.find_spec(entry["package"]) is not None
        out.append({
            **entry,
            "installed": installed,
            "install_hint": None if installed else f"pip install {entry['package']}",
        })
    return out
