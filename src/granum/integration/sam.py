"""Prompted Segment Anything masks. Callers decide whether to accept the proposal."""
from __future__ import annotations

from typing import Any

import numpy as np

from granum.errors import GranumError
from granum.formats.vision import encode_mask

SAM_MODELS = {"sam2.1_t.pt": "SAM 2.1 tiny", "sam2.1_s.pt": "SAM 2.1 small", "sam2.1_b.pt": "SAM 2.1 base", "mobile_sam.pt": "MobileSAM"}


def propose_mask(image: Any, *, model: Any = "sam2.1_t.pt", box: list[float] | None = None,
                 points: list[list[float]] | None = None, labels: list[int] | None = None) -> dict[str, Any]:
    width, height = image.size
    if width * height > 25_000_000:
        raise GranumError("interactive masks support images up to 25 million pixels")
    if not box and not points:
        raise GranumError("draw a box or provide a foreground point")
    if points and (not labels or len(labels) != len(points) or any(v not in (0, 1) for v in labels)):
        raise GranumError("each prompt point needs a foreground (1) or background (0) label")
    if not box and labels and 1 not in labels:
        raise GranumError("include at least one foreground point")
    if box and (len(box) != 4 or not np.isfinite(box).all() or not 0 <= box[0] < box[2] <= width or not 0 <= box[1] < box[3] <= height):
        raise GranumError("the prompt box must be inside the image")
    if points and (len(points) > 128 or any(len(p) != 2 or not np.isfinite(p).all() or not 0 <= p[0] <= width or not 0 <= p[1] <= height for p in points)):
        raise GranumError("prompt points must be inside the image (at most 128)")
    model_name = str(model) if isinstance(model, str) else type(model).__name__
    if isinstance(model, str):
        if model not in SAM_MODELS:
            raise GranumError("choose one of the supported SAM models")
        try:
            from ultralytics import SAM
        except ImportError as exc:
            raise GranumError("install Granum's training support to use SAM") from exc
        model = SAM(model)
    prompts: dict[str, Any] = {}
    if box:
        prompts["bboxes"] = [box]
    if points:
        # One object with several positive/negative prompts, not one object per point.
        prompts.update(points=[points], labels=[labels])
    results = model(image, **prompts, verbose=False, retina_masks=True)
    if not results or results[0].masks is None:
        raise GranumError("SAM did not propose a mask; adjust the prompts")
    masks = results[0].masks.data.cpu().numpy()
    if masks.ndim != 3 or masks.shape[1:] != (height, width) or not np.isfinite(masks).all():
        raise GranumError("SAM returned a mask that does not match the image")
    scores = results[0].boxes.conf.cpu().numpy() if results[0].boxes is not None else np.ones(len(masks))
    if len(scores) != len(masks) or not np.isfinite(scores).all():
        raise GranumError("SAM mask and quality counts differ")
    candidates = [{"mask": encode_mask(masks[i] > 0.5), "quality": float(scores[i])}
                  for i in np.argsort(-scores, kind="stable")[:3] if np.any(masks[i] > 0.5)]
    if not candidates:
        raise GranumError("SAM returned an empty mask; adjust the prompts")
    return {"model": model_name, "width": width, "height": height, "candidates": candidates}
