---
title: Images and thumbnails
summary: Reference image files, browse original media and create thumbnails without changing source pixels.
status: available
---

Granum stores image references alongside labels and measurements. Referencing an image does not copy
it into the workspace. Keep its location readable by the service and preserve the original when
moving a project.

## Register images

For classification, use a directory per class:

```python
from granum import Table

table = Table.from_image_folder(
    "/data/parts", project_name="inspection", dataset_name="train",
)
print(len(table), table.columns)
```

The source might contain `parts/acceptable/` and `parts/defect/`. Class-directory names determine the
class map. For unlabelled or mixed metadata, use `Table.from_dict_data` with an explicit
`ImageSchema(sample_type="url")`. Object-labelled images should enter through their annotation format.

## Browse the image and its evidence

Open Images, choose a set, and open a thumbnail. Use zoom and pan to inspect small objects. Labels,
predictions and review state have different meanings: a model prediction is evidence to review,
and a human label can still be wrong. [Annotation editing](/docs/guides/edit) saves a new table revision.

For large collections, generate thumbnails from the CLI:

```bash
granum thumbnails create /data/granum/projects/inspection/datasets/train/tables/initial
```

Replace the argument with the exact table or run URL from your workspace. The command reads referenced
images; it does not replace original images with lower-resolution copies. Use `--help` to inspect
options for your installed build.

## Paths and portability

The service checks whether media is referenced by an accessible table or active import. A file that
exists on your laptop is not automatically readable by a service running elsewhere. Configure
[data roots](/docs/operate/configuration) and [URL aliases](/docs/python/storage) on the machine that
reads the data.

When handing work to another machine, [export with copied media](/docs/improve/export) or create a
[portable backup](/docs/course/backup). A directory of metadata plus broken image links is not a
portable dataset. If thumbnails fail, inspect the source path, file permissions and supported image
encoding before retrying the import.
