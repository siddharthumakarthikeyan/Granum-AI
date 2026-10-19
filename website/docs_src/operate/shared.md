---
title: Share a workspace with a team
summary: Provision authenticated HTTPS access and understand the workspace-wide roles.
status: partial
---

Shared mode lets several people use one Granum service with authenticated accounts. All accounts can
read every project, media item, run and job exposed by that service. Use separate services/workspaces
when those readers must not have access to the same data.

## Provision accounts and HTTPS

Run account provisioning on the service host. The following paths and hostname are examples to replace
with administrator-controlled locations for your installation:

```bash
granum access add-user admin --role admin --file /secure/granum-users.json
granum access add-user reviewer --role reviewer --file /secure/granum-users.json
granum --project-root-url /srv/granum service --host 0.0.0.0   --auth-file /secure/granum-users.json   --tls-cert /secure/granum-cert.pem --tls-key /secure/granum-key.pem   --allow-host granum.example.org
```

Passwords are entered through the hidden prompt; the registry stores salted hashes. Keep the registry
and private key outside data roots and project backups. Use a certificate trusted by clients. Shared
HTTP Basic authentication requires HTTPS; unsupported non-loopback startup fails closed.

## Choose a role

| Role | Scope |
|---|---|
| Viewer | Read accessible workspace data and use supported read-only analysis |
| Annotator | Add annotation changes, comments, tags, views and exploratory versions |
| Reviewer | Also perform reviews, approval, recoverable curation and supported model/analysis jobs |
| Administrator | Full service management, including destructive and installation operations |

Shared writes derive the author from the authenticated account. A typed reviewer name in local mode
does not provide that same authentication. Changes and revocations in the registry require a service
restart; check existing jobs separately.

## Collaborate without losing edits

A stale base revision is rejected instead of silently overwriting another user's saved work. Retain
your draft, open the latest data and reconcile explicitly. Sharing an analysis workflow JSON transfers
view settings, while a shared service gives access to the actual workspace.

Read [operations](/docs/guides/operations) for audit-write failures, browser recovery and portable
backups. A filesystem administrator remains trusted; the logs are not tamper-proof attestations.

## Not yet included

Managed organisation accounts, granular per-project permissions, SAML/OIDC SSO, Azure Entra ID login,
API-key management and multi-tenant isolation are not yet included. Their scope is reserved under
[enterprise identity](/docs/planned/enterprise). Existing role-based shared access does not provide
those capabilities.
