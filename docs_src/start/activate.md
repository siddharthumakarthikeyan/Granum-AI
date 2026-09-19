---
title: Sign in and licences
summary: A free trial by email, plans counted per computer, and what changes when a licence ends.
---

Granum checks a signed licence on each computer. Open **Licence** at the bottom of the sidebar to see
what this computer has, when it ends, and how to change it.

## Start a trial

1. Open **Licence** and enter your email address.
2. Granum sends a six-digit code. Enter it.
3. The computer receives a licence: your plan if you have one, otherwise a **free trial — 7 days,
   one project**.

The code is valid for ten minutes. One trial per email address and one per computer: a second address on
the same machine, or the same address on a second machine, does not get another.

## Plans

Plans are counted in computers, not seats. A plan for five computers is one licence that five machines
can each claim a slot on. **Sign out** on the Licence page frees that machine's slot for another.

While the app is running and online it renews quietly every few hours. Away from the network it keeps
working for **seven days** on the lease it already holds; the Licence page shows how much of that is left.

## What "read-only" means

When a plan ends, a trial runs out or the offline lease expires, Granum turns read-only rather than
locking you out. This is deliberate: your data is yours, and you should always be able to get it back.

| Still works | Refused |
|---|---|
| Opening projects, browsing images and annotations | Importing or creating projects |
| Reading runs, dynamics, findings and comparisons | Editing labels, verifying, commenting |
| Exporting, copying files, the Python API for reading | Creating dataset versions, training |

Sign in again, or install a new key, and everything resumes where it was.

!!! note "Clock changes"
    The offline allowance is counted in running time on a monotonic clock, and Granum remembers the
    latest time it has seen. Moving the system clock backwards does not return offline days; it makes
    the app read-only until the clock is right again.

## Keys entered by hand

Computers that are never online can run on an **offline key** issued for a fixed period. Paste it into
the Licence page under *Enter a licence key*. Offline keys never renew: when the end date passes, the app
is read-only until a new key is installed.

Every key is issued for one computer and carries that computer's id (the `GM-…` shown on the Licence
page), so copying a key to another machine does not work.

## What the licence server is told

Only what an activation needs: your email address, the machine id, and the app version. No project names,
no file paths, no images, no annotations, no metrics. See [Privacy](/docs/help/privacy).
