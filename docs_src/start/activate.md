---
title: Alpha access and licences
summary: The current unrestricted alpha, written usage permission, and manually agreed pilots.
---

The current source and newly qualified **unrestricted-alpha** builds have licensing enforcement
disabled. They do not require in-app activation, enforce a trial countdown, limit the number of
projects for commercial reasons, or become read-only because a subscription expired.

## Permission and pilots

Granum remains proprietary. Removing a software quota does not grant usage, redistribution or
source-code rights. Evaluation permission, pilot scope, support and any fees are agreed in writing.
There is no automated checkout, automatic charge or active self-service subscription offer.

Use [the pilot form](/quote) to discuss requirements. Submitting it is not a purchase or a grant of rights.
Future releases may have different terms; they must disclose their enforcement policy explicitly.

## Download verification is separate

The website emails a code to verify a download request. That code does not start an in-app trial.
Downloads are published only after the operator supplies qualified release metadata, a source revision,
an artifact manifest and a SHA-256 checksum. A version number alone does not identify the exact build.

Older installers may not contain the latest source changes. Check `granum build-info` or the service's
`/api/health` build field against the manifest. An unstamped installer is not qualified as current.

## Offline and shared use

Local work needs no licence renewal in this alpha. Initial installation, optional model downloads and
cloud data can still need a network connection.

Shared-workspace authentication is separate from commercial licensing. A shared administrator creates
password-based accounts and configures HTTPS. Roles govern writes, but every account can read the whole
workspace. A machine licence is not a collaboration account or a tenant boundary.

## Legacy licensing machinery

Signed keys, trial issuance, machine slots and renewal APIs remain implemented and tested for explicitly
licensed builds. They do not describe the current alpha's restrictions. If an older build reports a
licence error, record its build identity and contact support rather than assuming current alpha rules
apply. See [Privacy](/docs/help/privacy).
