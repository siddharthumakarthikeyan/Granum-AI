---
title: Enterprise identity and delivery
summary: Reserved enterprise account, SSO, access-isolation and media-delivery capabilities.
status: planned
---

**Not yet included.** The sections below describe intended enterprise capabilities. The current
[single-workspace shared mode](/docs/operate/shared) already provides authenticated HTTPS and roles;
these reserved capabilities require additional implementation.

## Organisation accounts and API keys

Managed account signup, organisation membership, workspace invitations, service accounts, scoped API
keys and key rotation are not yet included. Existing shared accounts are provisioned on the service
host and have workspace-wide visibility.

Current unrestricted-alpha builds need no in-app licence activation. This does not create a managed
account platform or self-service paid subscription. See [access and licensing](/docs/start/activate)
for the behaviour of the current build.

## Single sign on

**Not yet included:** SAML or OIDC single sign-on, Azure Entra ID setup, identity-provider group mapping,
just-in-time account provisioning and central session revocation. The future guide will contain
supported protocols, callback configuration, certificate/key rotation and a tested login/recovery flow.
There are no supported Granum SSO environment variables to configure today.

## Access isolation

**Not yet included:** per-project permissions, multi-tenant data isolation and organisation-wide
assignment policies. All authenticated readers of one shared service can read that service's
workspace. Separate services and roots remain the current way to keep reader populations apart.

## Signed media delivery

**Not yet included:** browser-direct, self-authenticated cloud media URLs with bounded lifetime and
provider permissions. Media currently follows the configured service access path. The future guide
will need to explain URL lifetime, cache handling, revocation and the relationship to user access.

## Enterprise deployment lifecycle

A separately qualified enterprise control plane, offline entitlement workflow, managed updates,
central policy administration and enterprise support matrix are not yet included. Local/on-premise
service operation and manually provisioned shared HTTPS are documented today.

For present deployments, use [operations](/docs/guides/operations) for audit behaviour, backups,
recovery and upgrade rehearsal. Existing audit records are unsigned and filesystem administrators
remain trusted. Enterprise compliance claims are not implied by the availability of local logs.
