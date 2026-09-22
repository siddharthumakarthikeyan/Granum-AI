"""Image embeddings, and the questions one nearest-neighbour graph answers.

A vector per image turns five separate features into one computation:

``duplicates``   images that are the same picture again -- a resized copy, a re-export, the
                 next frame of a burst. Byte comparison finds only the first kind.
``exports``      one source picture written out several times by the exporter, usually with an
                 augmentation applied. Not duplicates: deleting them undoes the augmentation
                 somebody asked for. Told apart by the source name the exporter keeps in the
                 filename (:func:`source_key`), never by how alike two images look -- a flip of
                 a picture and another picture of the same street are equally close in here.
``leaks``        duplicates that straddle a split. A validation score measured on images the
                 model trained on is not a measurement, and filenames will not tell you.
``similar``      "show me more like this one", which is how a reviewer checks whether a
                 convention held across a set without scrolling through it.
``uniqueness``   how unlike the rest of the set an image is. Low uniqueness is redundancy you
                 can drop; high uniqueness is either the rare case worth keeping or a mistake.
``outliers``     images far from everything, which are usually the wrong picture entirely.

None of this needs labels or a trained model, so it works on a dataset the hour it arrives.

**Thresholds are relative, never absolute.** A cosine distance of 0.1 means something different
on aerial frames that all look alike than on a scrape of the open web, so every threshold here is
a fraction of the *typical distance between two images of this dataset*
(:func:`typical_distance`) -- the median over random pairs.

The unit has to be that rather than the median nearest-neighbour distance, which is the obvious
choice and is wrong: a dataset that is half export copies has a nearest-neighbour distance of
"me next to my own copy", and every threshold built on it collapses. This was measured, not
reasoned about. On an aerial dataset of 11,882 images whose filenames record which are exports of
one source frame (4,867 known copy pairs), with the default embedder:

===========================================  ========  ========  ========
group                                             p05    median       p95
===========================================  ========  ========  ========
the same photograph, exported twice            0.0074    0.0125    0.0214
another frame of the same capture sequence     0.1039    0.2590    0.4547
any two images                                 0.2417    0.3903    0.5716
===========================================  ========  ========  ========

At ``0.12`` of the typical distance, every one of those 4,867 copy pairs is found and no frame of
a merely-similar sequence is; at ``0.20`` the first false pairs appear. The defaults below sit in
that gap.

**Embeddings are keyed by image reference**, not row position, so they survive new versions of a
set exactly as review decisions do (see :mod:`granum.core.reviews`).

The default embedder is a small ImageNet network, because it is already on the machine once the
training add-on is installed, runs on CPU at a few hundred images a second, and is deterministic.
Without the add-on a plain descriptor is used instead: it finds resizes and re-encodes reliably
and semantic neighbours only roughly, and :func:`describe_embedder` says so rather than letting a
reader assume otherwise.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass
from typing import Any

import numpy as np

EMBEDDINGS_VERSION = "embeddings-1"

#: Embedders, best first. The first one whose requirements are installed is used.
EMBEDDERS: dict[str, dict[str, Any]] = {
    "mobilenet_v3_small": {
        "name": "MobileNetV3 small",
        "dimensions": 576,
        "needs": "torch",
        "detail": "ImageNet features. Groups images by what is in them, not only by how they look.",
    },
    "resnet18": {
        "name": "ResNet-18",
        "dimensions": 512,
        "needs": "torch",
        "detail": "ImageNet features, a little slower and a little stronger than MobileNet.",
    },
    "descriptor": {
        "name": "Plain descriptor",
        "dimensions": 704,
        "needs": None,
        "detail": "Colour and edge layout only. Finds copies and resizes; not a judge of content.",
    },
}


@dataclass(frozen=True)
class NeighbourPolicy:
    #: Neighbours kept per image. Also the neighbourhood uniqueness reads.
    k: int = 15
    #: Closer than this fraction of the typical distance and it is the same photograph again.
    #: Measured: catches every known export copy, and nothing that is merely similar.
    duplicate: float = 0.12
    #: Closer than this and two images should not be on opposite sides of a split -- wide enough
    #: to include neighbouring frames of one capture sequence, which leak just as badly.
    leak: float = 0.30
    #: An image whose nearest neighbour is further than this has nothing like it in the set.
    outlier: float = 0.90
    #: A "duplicate group" larger than this is not a pile of copies but a continuum -- frames of
    #: one long take, a burst, a slow pan -- where each image is near the next and no pair is a
    #: copy of anything. Reported apart, because "these 900 images are duplicates" would be false.
    max_group: int = 40
    #: Images to embed in one forward pass.
    batch: int = 32

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


#: How exporters spell "this file came from that picture". Roboflow, which is how most of these
#: datasets arrive, writes ``<original stem>_<ext>.rf.<32 hex>.<ext>`` and gives each export of
#: one source its own hash, so the stem is the source and the hash is the copy.
_EXPORT_NAME = re.compile(r"^(?P<stem>.+?)(?:_[A-Za-z0-9]+)?\.rf\.[0-9a-f]{16,}\.[A-Za-z0-9]+$")


def source_key(image: str, augmented_from: str | None = None) -> str:
    """Which original picture an image is a copy of, as far as its name can say.

    Augmentation makes a picture that *is* the same picture: a flip, a crop, a colour shift.
    No distance threshold can separate that from a second photograph of the same thing, and it
    must be separated, because one is redundancy to remove and the other is training data
    somebody deliberately made. What can separate them is provenance, and exporters record it:
    Granum's own augmented sets carry ``augmented_from``, and a Roboflow export keeps the source
    name in every copy's filename.

    The folder is dropped on purpose, so that two exports of one picture are recognised as one
    source even when they were dealt into different splits -- which is exactly the case that
    matters, because that is a leak. An image whose name says nothing is its own source.
    """
    if augmented_from:
        return str(augmented_from)
    name = str(image).replace("\\", "/").rsplit("/", 1)[-1]
    match = _EXPORT_NAME.match(name)
    return match.group("stem") if match else str(image)


def source_families(sources: Sequence[str]) -> dict[str, list[int]]:
    """The rows of each source picture, in the order they were given."""
    families: dict[str, list[int]] = {}
    for row, key in enumerate(sources):
        families.setdefault(key, []).append(row)
    return families


def describe_embedder(key: str) -> dict[str, Any]:
    """What an embedder is, in terms a reader can weigh, including what it cannot do."""
    info = dict(EMBEDDERS.get(key) or EMBEDDERS["descriptor"])
    info["id"] = key
    info["semantic"] = key != "descriptor"
    return info


def available_embedder(preferred: str | None = None) -> str:
    """The best embedder installed on this machine, or ``preferred`` when it is usable."""
    try:  # noqa: SIM105 - the add-on is optional by design
        import torch  # noqa: F401

        has_torch = True
    except Exception:  # noqa: BLE001 - any import failure means "not available"
        has_torch = False
    if preferred and (has_torch or EMBEDDERS.get(preferred, {}).get("needs") is None):
        return preferred
    return "mobilenet_v3_small" if has_torch else "descriptor"


# ---------------------------------------------------------------------------
# computing vectors
# ---------------------------------------------------------------------------


def _descriptor(image: Any) -> np.ndarray:
    """A small, dependency-free vector: coarse colour by cell, plus edge direction by cell.

    Deliberately simple. It answers "is this the same picture" well and "is this the same kind
    of thing" only roughly, which is the honest boundary of what pixels alone can say.
    """
    from PIL import Image

    grid = image.convert("RGB").resize((32, 32), Image.BILINEAR)
    pixels = np.asarray(grid, dtype=np.float32) / 255.0
    # Colour: mean RGB over 8x8 cells of the 32x32 thumbnail.
    cells = pixels.reshape(8, 4, 8, 4, 3).mean(axis=(1, 3))
    grey = pixels.mean(axis=2)
    dx = np.diff(grey, axis=1, prepend=grey[:, :1])
    dy = np.diff(grey, axis=0, prepend=grey[:1, :])
    angle = (np.arctan2(dy, dx) + np.pi) / (2 * np.pi)  # 0..1
    strength = np.hypot(dx, dy)
    # Edges: an 8-bin direction histogram, weighted by strength, per 8x8 cell. Accumulated in
    # one scatter-add rather than a Python loop: this runs once per image in the dataset.
    bins = np.clip((angle * 8).astype(np.int32), 0, 7)
    rows, columns = np.divmod(np.arange(32 * 32), 32)
    flat = ((rows // 4) * 8 + (columns // 4)) * 8 + bins.reshape(-1)
    edges = np.zeros(8 * 8 * 8, dtype=np.float32)
    np.add.at(edges, flat, strength.reshape(-1))
    return np.concatenate([cells.reshape(-1), edges]).astype(np.float32)


def _torch_model(key: str) -> tuple[Any, Any]:
    import torch
    from torchvision import models, transforms

    if key == "resnet18":
        net = models.resnet18(weights=models.ResNet18_Weights.IMAGENET1K_V1)
        net.fc = torch.nn.Identity()
    else:
        net = models.mobilenet_v3_small(weights=models.MobileNet_V3_Small_Weights.IMAGENET1K_V1)
        net.classifier = torch.nn.Identity()
    net.eval()
    prepare = transforms.Compose([
        transforms.Resize(232),
        transforms.CenterCrop(224),
        transforms.ToTensor(),
        transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]),
    ])
    return net, prepare


def embed_images(
    paths: Sequence[str],
    *,
    embedder: str | None = None,
    policy: NeighbourPolicy = NeighbourPolicy(),
    progress: Any = None,
    device: str | None = None,
) -> tuple[np.ndarray, list[int]]:
    """Embed every image, L2-normalised, one row each.

    ``device`` forces where a neural embedder runs (``"cpu"`` while a training job holds the GPU).

    Returns the vectors and the positions of images that could not be read, so the caller can
    report them rather than silently embedding a smaller set than it asked for.
    """
    from PIL import Image

    key = available_embedder(embedder)
    failed: list[int] = []
    if key == "descriptor":
        rows: list[np.ndarray] = []
        for index, path in enumerate(paths):
            try:
                with Image.open(path) as image:
                    rows.append(_descriptor(image))
            except Exception:  # noqa: BLE001 - an unreadable image is reported, not fatal
                rows.append(np.zeros(EMBEDDERS["descriptor"]["dimensions"], dtype=np.float32))
                failed.append(index)
            if progress is not None and index % 50 == 0:
                progress(index + 1, len(paths))
        vectors = np.vstack(rows) if rows else np.zeros((0, EMBEDDERS["descriptor"]["dimensions"]), np.float32)
        return normalise(vectors), failed

    import torch

    net, prepare = _torch_model(key)
    # The GPU is the training job's; embedding is small enough to leave it alone when asked.
    device = device or ("cuda" if torch.cuda.is_available() else "cpu")
    net = net.to(device)
    out: list[np.ndarray] = []
    with torch.no_grad():
        for start in range(0, len(paths), policy.batch):
            batch = []
            for index, path in enumerate(paths[start:start + policy.batch], start=start):
                try:
                    with Image.open(path) as image:
                        batch.append(prepare(image.convert("RGB")))
                except Exception:  # noqa: BLE001
                    batch.append(torch.zeros(3, 224, 224))
                    failed.append(index)
            features = net(torch.stack(batch).to(device))
            out.append(features.detach().cpu().numpy().astype(np.float32))
            if progress is not None:
                progress(min(start + policy.batch, len(paths)), len(paths))
    vectors = np.vstack(out) if out else np.zeros((0, EMBEDDERS[key]["dimensions"]), np.float32)
    return normalise(vectors), failed


def normalise(vectors: np.ndarray) -> np.ndarray:
    """Unit vectors, so cosine distance is ``1 - dot`` and nothing depends on brightness scale."""
    vectors = np.asarray(vectors, dtype=np.float32)
    if vectors.size == 0:
        return vectors.reshape(0, vectors.shape[-1] if vectors.ndim > 1 else 0)
    lengths = np.linalg.norm(vectors, axis=1, keepdims=True)
    return vectors / np.maximum(lengths, 1e-12)


# ---------------------------------------------------------------------------
# the neighbour graph
# ---------------------------------------------------------------------------


def neighbours(vectors: np.ndarray, k: int = 15, *, chunk: int = 512) -> tuple[np.ndarray, np.ndarray]:
    """For every image, its ``k`` nearest others: their indices and cosine distances.

    Computed in chunks, so a set of 100,000 images needs a 100,000 x 512 block rather than a
    square matrix of itself.
    """
    count = len(vectors)
    if count == 0:
        return np.zeros((0, 0), np.int32), np.zeros((0, 0), np.float32)
    width = int(min(k, max(count - 1, 1)))
    index = np.zeros((count, width), np.int32)
    distance = np.zeros((count, width), np.float32)
    for start in range(0, count, chunk):
        block = vectors[start:start + chunk]
        similarity = block @ vectors.T
        # An image is always its own nearest neighbour; that says nothing.
        for row in range(len(block)):
            similarity[row, start + row] = -np.inf
        take = np.argpartition(-similarity, width - 1, axis=1)[:, :width]
        ordered = np.take_along_axis(similarity, take, axis=1)
        order = np.argsort(-ordered, axis=1)
        picked = np.take_along_axis(take, order, axis=1)
        index[start:start + len(block)] = picked
        distance[start:start + len(block)] = 1.0 - np.take_along_axis(similarity, picked, axis=1)
    return index, np.clip(distance, 0.0, 2.0)


def typical_distance(vectors: np.ndarray, *, pairs: int = 4000, seed: int = 0) -> float:
    """How far apart two images of this dataset usually are: the median over random pairs.

    The unit every threshold is expressed in. Sampled rather than exhaustive, because the median
    of a few thousand pairs is stable to three decimal places and an exhaustive computation is
    quadratic. Unaffected by how many duplicates the set holds, which is the whole point.
    """
    if len(vectors) < 2:
        return 1.0
    generator = np.random.default_rng(seed)
    left = generator.integers(0, len(vectors), pairs)
    right = generator.integers(0, len(vectors), pairs)
    keep = left != right
    if not keep.any():
        return 1.0
    gaps = 1.0 - np.einsum("ij,ij->i", vectors[left[keep]], vectors[right[keep]])
    return float(max(np.median(gaps), 1e-6))


def duplicate_groups(
    index: np.ndarray,
    distance: np.ndarray,
    scale: float,
    policy: NeighbourPolicy = NeighbourPolicy(),
    *,
    factor: float | None = None,
) -> list[list[int]]:
    """Groups of images that are the same picture again, largest group first.

    Transitive: A near B and B near C puts all three in one group, because a set of re-exports
    usually arrives as a chain of small differences rather than as exact pairs. That chaining is
    also why :func:`split_chains` exists -- on a continuum it would otherwise swallow the set.
    """
    if len(index) == 0:
        return []
    limit = (factor if factor is not None else policy.duplicate) * scale
    parent = list(range(len(index)))

    def root(node: int) -> int:
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    for row in range(len(index)):
        for other, gap in zip(index[row], distance[row]):
            if gap <= limit:
                a, b = root(row), root(int(other))
                if a != b:
                    parent[a] = b
    groups: dict[int, list[int]] = {}
    for node in range(len(index)):
        groups.setdefault(root(node), []).append(node)
    found = [sorted(members) for members in groups.values() if len(members) > 1]
    found.sort(key=lambda members: (-len(members), members[0]))
    return found


def split_chains(
    groups: Sequence[Sequence[int]], policy: NeighbourPolicy = NeighbourPolicy()
) -> tuple[list[list[int]], list[list[int]]]:
    """Separate real copy groups from continuums, by size.

    A handful of images that are all within a copy's distance of each other is a copy group. Nine
    hundred of them is a video: every frame close to the next, no two the same photograph. Calling
    the second one "duplicates" would be a false statement, so it is reported as its own thing.
    """
    duplicates = [list(group) for group in groups if len(group) <= policy.max_group]
    chains = [list(group) for group in groups if len(group) > policy.max_group]
    return duplicates, chains


def group_spread(vectors: np.ndarray, members: Sequence[int], scale: float) -> float:
    """How far apart the two least alike images of a group are, as a share of the typical distance.

    Groups are built by chaining -- A near B and B near C puts all three together -- so their
    members are not all near one another. Re-exports of one photograph have a spread close to
    zero; frames of one fixed camera, each a little different from the last, chain into a group
    with a visible spread. That number is the difference between "this image is in here twice"
    and "this sequence is worth thinning", and only the reader can decide the second.
    """
    if len(members) < 2 or scale <= 0:
        return 0.0
    block = vectors[list(members)]
    return float(np.max(1.0 - block @ block.T) / scale)


def uniqueness(index: np.ndarray, distance: np.ndarray, scale: float,
               policy: NeighbourPolicy = NeighbourPolicy()) -> np.ndarray:
    """How unlike the rest of the set each image is, from 0 (a copy) to 1 (nothing like it).

    The nearest neighbours count for more than the further ones, so one exact copy is enough to
    make an image unremarkable however unusual the rest of its neighbourhood is. The result is
    divided by the set's own scale and squashed, so it reads as a share and compares between
    datasets rather than being a raw distance.
    """
    if distance.size == 0:
        return np.zeros(0, np.float32)
    width = min(policy.k, distance.shape[1])
    weights = 1.0 / np.arange(1, width + 1, dtype=np.float32)
    weighted = (distance[:, :width] * weights).sum(axis=1) / weights.sum()
    return np.clip(weighted / (weighted + scale), 0.0, 1.0).astype(np.float32)


def outlier_scores(distance: np.ndarray, scale: float) -> np.ndarray:
    """Distance to the nearest neighbour, as a fraction of the typical distance.

    Above ``NeighbourPolicy.outlier`` an image has nothing like it in the set. That is a flag to
    look, not a verdict: the rarest class in a dataset lives here too.
    """
    if distance.size == 0:
        return np.zeros(0, np.float32)
    return (distance[:, 0] / scale).astype(np.float32)


def leaks(
    index: np.ndarray,
    distance: np.ndarray,
    sets: Sequence[str],
    scale: float,
    policy: NeighbourPolicy = NeighbourPolicy(),
    *,
    sources: Sequence[str] | None = None,
    vectors: np.ndarray | None = None,
) -> list[dict[str, Any]]:
    """Pairs of near-identical images that sit in different sets, worst first.

    This is the check that decides whether a validation score means anything, and it is the one
    thing in this module that is closer to a verdict than a suggestion: an image that is also in
    the training set is not a measurement of anything.

    An augmented copy leaks exactly as badly as an exact one, and can be far enough away in the
    embedding to miss the threshold -- a heavy colour shift is not a small distance. So when the
    sources are known, every pair of exports of one picture that straddles a split is reported
    too, whatever the distance between them.
    """
    limit = policy.leak * scale
    seen: set[tuple[int, int]] = set()
    found: list[dict[str, Any]] = []

    def add(a: int, b: int, gap: float) -> None:
        pair = (min(a, b), max(a, b))
        if pair in seen:
            return
        seen.add(pair)
        found.append({
            "a": pair[0], "b": pair[1],
            "sets": [sets[pair[0]], sets[pair[1]]],
            "distance": round(float(gap), 4),
            # Under the duplicate threshold it is the same photograph; above it, a frame
            # close enough that training on one teaches the model the other.
            "same_image": bool(gap <= policy.duplicate * scale),
            # Both sides are the exporter's copies of one picture: not a coincidence to weigh
            # up, a split that was cut after the copies were made.
            "same_source": bool(sources is not None and sources[pair[0]] == sources[pair[1]]),
        })

    for row in range(len(index)):
        for other, gap in zip(index[row], distance[row]):
            other = int(other)
            if gap <= limit and sets[row] != sets[other]:
                add(row, other, float(gap))
    if sources is not None and vectors is not None:
        for members in source_families(sources).values():
            if len(members) < 2 or len({sets[row] for row in members}) < 2:
                continue
            for at, row in enumerate(members):
                for other in members[at + 1:]:
                    if sets[row] != sets[other]:
                        add(row, other, float(1.0 - vectors[row] @ vectors[other]))
    found.sort(key=lambda item: item["distance"])
    return found


def similar_to(
    vectors: np.ndarray,
    row: int,
    k: int = 24,
) -> list[tuple[int, float]]:
    """The ``k`` images most like one image: its index and distance, nearest first."""
    if len(vectors) == 0 or not 0 <= row < len(vectors):
        return []
    similarity = vectors @ vectors[row]
    similarity[row] = -np.inf
    width = int(min(k, len(vectors) - 1))
    if width <= 0:
        return []
    take = np.argpartition(-similarity, width - 1)[:width]
    take = take[np.argsort(-similarity[take])]
    return [(int(i), round(float(1 - similarity[i]), 4)) for i in take]


def project(vectors: np.ndarray, *, seed: int = 0) -> np.ndarray:
    """A 2D layout of the set for a map view, by PCA: deterministic, and fast enough to redo.

    PCA rather than UMAP or t-SNE on purpose: it needs no extra dependency, it is the same
    picture every time, and distances in it can be explained. A nonlinear layout looks better
    and invites conclusions the projection does not support.
    """
    if len(vectors) < 2:
        return np.zeros((len(vectors), 2), np.float32)
    centred = vectors - vectors.mean(axis=0, keepdims=True)
    generator = np.random.default_rng(seed)
    # Randomised SVD: only the first two components are wanted, and the matrix is wide.
    sketch = centred @ generator.normal(size=(centred.shape[1], 8)).astype(np.float32)
    basis, _ = np.linalg.qr(sketch)
    small = basis.T @ centred
    _, _, rotation = np.linalg.svd(small, full_matrices=False)
    points = centred @ rotation[:2].T
    span = np.maximum(points.max(axis=0) - points.min(axis=0), 1e-9)
    return (((points - points.min(axis=0)) / span) * 2 - 1).astype(np.float32)


def summarise(
    keys: Sequence[str],
    sets: Sequence[str],
    vectors: np.ndarray,
    index: np.ndarray,
    distance: np.ndarray,
    policy: NeighbourPolicy = NeighbourPolicy(),
    sources: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Everything the graph says about a set, as one payload for the dashboard.

    Groups are sorted into two kinds before anything is counted, because they mean opposite
    things. A group holding more than one source picture is redundancy: the same photograph
    arrived twice and one of them can go. A group that is one source picture written out several
    times is the exporter's augmentation, and removing it would undo work somebody asked for --
    so it is reported, with its own count, and never as something to delete.
    """
    scale = typical_distance(vectors)
    keys = list(keys)
    sources = [source_key(key) for key in keys] if sources is None else list(sources)
    families = source_families(sources)
    groups, chains = split_chains(duplicate_groups(index, distance, scale, policy), policy)
    # A group of one family is the same picture exported again, however alike its members look.
    copies = [members for members in groups if len({sources[i] for i in members}) > 1]
    unique = uniqueness(index, distance, scale, policy)
    outliers = outlier_scores(distance, scale)
    crossing = leaks(index, distance, sets, scale, policy, sources=sources, vectors=vectors)
    repeated = {key: rows for key, rows in families.items() if len(rows) > 1}
    return {
        "version": EMBEDDINGS_VERSION,
        "images": len(keys),
        "policy": policy.to_dict(),
        "scale": round(scale, 4),
        "duplicates": {
            "groups": [[keys[i] for i in members] for members in copies],
            # Per group, in the same order: how alike its least alike pair is.
            "spreads": [round(group_spread(vectors, members, scale), 4) for members in copies],
            # Per group, one small number per image: which of the group's source pictures it is
            # a copy of. Two images sharing a number are one picture, not a repetition of it.
            "families": [_family_numbers(members, sources) for members in copies],
            "images": int(sum(len(members) for members in copies)),
            # Source pictures that repeat another source picture: what there is to remove.
            "redundant": int(sum(len({sources[i] for i in members}) - 1 for members in copies)),
        },
        # The exporter's own copies: one picture written out more than once, augmented or not.
        "exports": {
            "sources": len(families),
            "repeated": len(repeated),
            "images": int(sum(len(rows) for rows in repeated.values())),
            "groups": [
                {"source": key, "images": [keys[row] for row in rows],
                 "sets": sorted({sets[row] for row in rows})}
                for key, rows in sorted(repeated.items(), key=lambda item: (-len(item[1]), item[0]))
            ],
        },
        # Runs of images each close to the next: a burst, a pan, video frames. Not copies.
        "chains": [{"images": len(members), "example": keys[members[0]],
                    "sets": sorted({sets[i] for i in members})} for members in chains],
        "leaks": [{**item, "a": keys[item["a"]], "b": keys[item["b"]]} for item in crossing],
        "uniqueness": {key: round(float(value), 4) for key, value in zip(keys, unique)},
        # The images furthest from anything else, whether or not any of them is far enough to
        # be called alone. A set of one subject taken by one camera has no image past the
        # threshold and still has a furthest one, and that is what a reader came to look at;
        # `alone` marks the ones the policy does call isolated.
        "outliers": [
            {"image": keys[i], "score": round(float(outliers[i]), 3), "set": sets[i],
             "alone": bool(outliers[i] >= policy.outlier)}
            for i in np.argsort(-outliers)[:200]
        ],
    }


def _family_numbers(members: Sequence[int], sources: Sequence[str]) -> list[int]:
    """Number each image of a group by which source picture it came from, 0 upwards."""
    numbers: dict[str, int] = {}
    return [numbers.setdefault(sources[row], len(numbers)) for row in members]


def iter_batches(items: Iterable[Any], size: int) -> Iterable[list[Any]]:
    batch: list[Any] = []
    for item in items:
        batch.append(item)
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch
