---
title: Advanced analysis extensions
summary: Reserved space for additional operators, derived views, component plots and retrieval analysis.
status: planned
---

**Not yet included.** The capabilities below have reserved documentation sections. Current
[calculations](/docs/explore/calculations), [charts](/docs/explore/charts) and
[workflows](/docs/explore/workflows) remain available within their documented scope.

## Additional calculation operators

**Not yet included:** a complete array/text/time/geometry expression catalogue. Reserved families
include array indexing and unrolling, vector sorting/median/uniqueness, vector normalisation, string
parsing and word counts, filename extraction, datetime components, hashes, constants, general boolean
composition and arbitrary nested-property extraction.

Also reserved are general binning, threshold clustering, traversal ordering, nearest-neighbour links,
group-neighbour links, link-distance operations and automatic category encodings. The image duplicate
workflow has its own neighbour analysis; it does not expose all these as general column operators.

Ordered scalar differences are available. A full vector derivative/deviation and chained reduction
operator library remains reserved. Geometry area/volume/line/triangle calculations and general
cross-geometry matching expressions need explicit data contracts before their reference can be added.

## Additional plot and view types

**Not yet included:** a guided N-component/parallel-coordinate chart, dedicated reduced-table tabs,
dynamically reduced charts and arbitrary multi-table/multi-run view composition. A reduced table
would group rows by chosen keys and materialise aggregate measurements. This is different from
reducing the dimensions of embeddings, which is already available.

For now, use explicit Python aggregation to create a new typed table, the existing linked scatter/image
charts, or the supported two-run comparison screen. A general saved subset-tab interface is also
reserved; persisted Python subsets and dashboard dataset versions are available alternatives.

## Retrieval and cross table analysis

**Not yet included:** question-to-chunk and chunk-to-question relationships, retrieval candidate links,
before/after semantic matches, embedding-distance comparisons, semantic similarity changes,
selection-relative chunk relationships and interactive foreign-table operations.

Run metrics already join to their registered input samples. That specific join does not provide a
general foreign-table query language, edited-row relationships or a retrieval evaluation product.
This section will need a worked question/document dataset, identity rules and interpretation of
retrieval scores before it can become a usage guide.

## Sampling and selection

**Not yet included:** optimised weighted coreset selection, persisted 3D volume selection and a general
multi-column travel-distance wizard. Use [weight-aware samplers](/docs/improve/weights), explicitly
saved subsets and the documented screen-space 3D selection behaviour today.

Each future guide will identify its inputs, calculation scope, saved output and missing-value rules.
No release date or executable interface is implied by these reserved sections.
