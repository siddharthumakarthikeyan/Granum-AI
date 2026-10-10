# Maintaining the guided aerial course

## Sources of truth

- Narrative: `docs_src/course/*.md`; the entry point is `/docs/course/start`.
- Navigation/order: `NAV` in `tools/docs.py`. New pages must be added there.
- Published assets: `public/assets/course`. **Do not put media under `public/docs`**: the builder cleans
  unknown files from that directory.
- Actual capture metadata: one JSON and WebVTT per video, plus `evidence.json` and
  `operations-evidence.json`. Preserve weak/zero results rather than replacing them with illustrative scores.
- Real subset: `aerial-mini.zip`, its SHA-256 sidecar, attribution and embedded manifest.

The course is 12 numbered lessons plus an introduction. It contains 35 application screenshots and
10 silent captioned clips. Source capture: Linux, Granum 0.1.0 checkout, Chromium 1440×960 on 2 October
2026. This is not installer, all-platform or enterprise qualification.

## Build, preview and test

From this repository, with its Python requirements installed:

```bash
python3 tools/docs.py
python3 tools/docs.py --check
python3 tools/preview_docs.py --port 18863
```

The preview serves clean URLs like the public site and binds only to loopback. It does not start the
licence service or contact a production database. It is not a production server. From another terminal:

```bash
env -u TEST_DATABASE_URL PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest -o addopts='' -q tests
node ../granum/web/scripts/check-course.mjs
```

The browser check needs the sibling Granum dashboard's installed Playwright/Chromium dependencies.
It checks every lesson at desktop and mobile sizes, decodes the real images and all ten MP4s, loads
captions, exercises full-text search and checks keyboard focus. Preview screenshots stay in Granum's
ignored build directory, not the public asset set.

Tests verify the distributed archive, source-selection safety, caption/metadata consistency, lesson
requirements, media targets, generated HTML, internal links/anchors and search coverage. Some assertions
intentionally pin the published measured result. A new experiment requires reviewing the prose and
evidence together—not changing expected values just to make tests pass.

## Recreate the source subset

The source export is the workspace's `dataset/human_aerial`, not the built-in shapes fixture. It is
read-only input. Its supplied licence notice declares CC BY 4.0; that is not independent proof of
upstream ownership. Keep attribution and check intended-use rights before redistribution.

Run from the parent workspace, choosing **new** output paths:

```bash
python3 granum-website/tools/prepare_walkthrough.py \
  --source dataset/human_aerial \
  --target /tmp/granum-course-new/aerial-mini \
  --archive /tmp/granum-course-new/aerial-mini.zip
```

The helper verifies the source's byte-identical validation/test annotations and all corresponding media,
then selects 96 train and 24 valid images with seed 20261002. It excludes repeated selected frames,
byte-identical selected images and train filename-prefix sequences present in source validation.
Prefix grouping is a heuristic, not proof of scene independence. Image bytes and selected source
annotation objects are retained; the import separately records duplicate-name and ignore-region decisions.

Existing outputs, traversal/absolute image paths, symlink escapes, an archive inside the extraction
target and outputs inside source data are refused. The sample is 26.4 MiB; raw source data, model weights
and training output must not be committed as public course media.

## Record actual application state

The recorder lives in the sibling main repository under `web/scripts/record-course.mjs` and
`web/scripts/course-chapters.mjs`. It operates on a dedicated project named aerial-walkthrough. Never
point it at a customer's workspace. It performs real writes, training, individual reviews and approval.

1. Build the dashboard using its normal `npm run build` command.
2. Start `granum/tools/serve_walkthrough.py` with a new dedicated `--workspace`, extracted `--data`
   directory and `--port 18861`. It ignores ambient Granum config/env roots and binds only to loopback.
3. Run chapters `01-import`, `02-browse`, then **`04-versions` before `03-review`**. The full baseline
   must be frozen before practice edits/review.
4. Run `05-train`. Wait for the real three-epoch job to finish in the UI; `06-results` refuses a missing
   completed baseline. Do not manufacture metrics or use a mocked API to make the clip succeed.
5. Run `07-experiment` on the same frozen baseline. After the actual twelve-epoch job finishes, run
   `08-compare` to capture the compatibility checks and write the measured evidence JSON.
6. Run `09-handoff` only after actually inspecting the two documented images. It creates and approves
   a two-image excerpt; no full-sample approval is claimed.
7. Stop writers. Run the course's actual integrity/backup/restore commands into a separate root. Check
   original/restored hashes and sizes, relocated media paths, reviews, run references and release state.
8. Start the isolated service on the restored root and run `10-restore` with
   `GRANUM_COURSE_PROJECT=aerial-restored`. This shows the restored UI, not the offline CLI execution.

Each invocation is `node granum/web/scripts/record-course.mjs CHAPTER` from the parent workspace.
`GRANUM_COURSE_URL` can override the default service origin. Chromium, FFmpeg with libx264/libwebp and the
dashboard's Playwright package are prerequisites. Model dependencies and hardware are separate.

The runner exports WebP screenshots, H.264/yuv420p MP4s with faststart, captions and capture metadata.
Caption timing is normalized to the encoded video duration, not assumed equal to the automation wall
clock; the original duration/cues remain in metadata. `course-media.mjs` can regenerate timing for an
existing generated asset directory without rerunning application writes. The browser check compares
the actual decoded duration with metadata and loads each caption track.
Raw PNG/WebM files and failure captures stay under `granum/build/course-recordings`. Failed chapters do
not publish a success video; inspect partial screenshots before reusing them. Successful reruns replace
generated assets, so preserve an existing published set before starting a replacement capture.

The deliberate relabel in recovery practice is restored before saving, and the runner compares stored
boxes with the original. It is not evidence of a source-label correction. The two verified images must
still be personally inspected; do not bulk-verify the dataset to make approval pass.

## Before publishing a documentation update

- Review every changed narrative assertion against the source and observed UI.
- Keep metrics/evaluator/threshold/checkpoint definitions distinct.
- Check sample checksum, attribution, counts and holdout limitations.
- Embed native video controls, a poster, English WebVTT captions and a transcript; no autoplay.
- Give each screenshot a useful alt description and full-resolution link.
- Run build/check, tests and desktop/mobile browser validation.
- Confirm only compressed media/sample assets are public; no credentials, private projects, weights or raw recordings.
- Publish the generated HTML, search index, CSS/JS and assets together. An archive's START-HERE link must resolve.
- Do not set installer release qualification flags merely because the documentation is ready.