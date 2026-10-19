---
title: Builds and release information
summary: Identify the build you are using and distinguish development documentation from qualified desktop artifacts.
status: partial
---

Granum's current package version is `0.1.0`, and the public channel is unrestricted alpha. Multiple
source revisions can share that version string. Identify a build using its source revision and
manifest, especially when following documentation for newly added features.

## Inspect your build

```bash
granum version
granum build-info
```

The running service's `/api/health` response also exposes build identity. Keep the artifact checksum
and manifest supplied with a desktop download. Compare these with the build intended for your
workspace; a newer-looking filename is not a substitute for matching provenance.

## Development documentation

The feature index describes the current development source reviewed on 19 October 2026. Some guides
cover code newer than the last qualified installer. **Available** describes the documented capability
in that source; it does not certify every operating system, GPU or dataset.

Check the guide's dependencies and limitations. A partially included integration can offer useful
functions while leaving a specialised task or deployment unsupported. **Not yet included** pages
reserve scope without promising an installation command or delivery date.

## Desktop publication

The download site offers artifacts that pass its publication metadata gate. Development builds and
qualified public downloads are distinct. Installation, import/edit/reload, training where promised,
backup/restore and upgrade behaviour still need platform-specific qualification.

Current alpha access does not enforce a timed trial or paid quota in the application. See
[access and licences](/docs/start/activate) for the applicable product behaviour.

## Release notes archive

**Not yet included.** A curated per-release changelog with separate dashboard, Python and service
compatibility notes has a reserved place here. Future entries should identify exact revisions,
behaviour changes, migration instructions and remaining limitations.

Another product's historical version numbers are not Granum releases. Use
[upgrade rehearsal](/docs/operate/upgrades) for current migration guidance and retain a known working
artifact plus a recoverable workspace before switching builds.
