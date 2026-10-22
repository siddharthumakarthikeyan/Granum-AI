---
title: Point clouds and 3D annotations
summary: Reserved ingestion, visualisation and editing for spatial datasets and synchronised sensors.
status: planned
---

**Not yet included.** Granum does not currently provide a complete point-cloud data model, dedicated
3D annotation editor or sensor-sequence import workflow.

## Spatial data types

This section is reserved for point clouds, meshes, three-dimensional points, lines and triangles,
3D bounding boxes/cuboids, coordinate frames, units and per-point or per-object attributes. A usable
workflow must specify which coordinate system each label belongs to and how transformations affect it.

Future type guides will include a small input, its schema, supported storage representation and a
round-trip export check. They will distinguish geometric data from an embedding vector that happens
to contain three numbers.

## Annotation and inspection

Reserved editor capabilities include selecting points or volumes, placing and rotating cuboids,
inspecting occlusion, linking cameras to spatial views and applying per-point labels. Their save,
review and revision semantics need to be defined alongside their interaction controls.

The current [3D scatter plot](/docs/explore/charts#work-in-three-dimensions) displays numeric observations
and supports screen-space selection. It does not make this annotation workflow available. Its
selection is based on projected centres at all depths, not a persisted spatial volume.

## Sensor datasets

**Not yet included:** PandaSet ingestion, synchronised camera/LiDAR views, multi-sensor calibration,
point-cloud sequence playback and a worked autonomous-driving example. The reserved guide will need
to preserve sequence identity, timestamps, calibration and train/evaluation grouping.

For externally prepared image-only portions, supported image imports remain available. Keep their
sequence and sensor metadata so the reduction to images is explicit; do not describe the result as
a complete spatial dataset import.

## Current alternatives

Keep spatial annotation in your existing tool, export the image or scalar measurements Granum can
represent, and attach model observations through [Python tables](/docs/python/tables). Use linked
identifiers if you need to trace results back to the original spatial record.

This page will gain supported formats, import commands, editor examples and validation checks with the
implementation. No point-cloud importer or 3D training API is being promised by the reserved page.
