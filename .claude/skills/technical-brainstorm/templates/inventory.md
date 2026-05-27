# Inventory

This file is the **authoritative list of components in scope** — services, repos, packages, databases, external integrations. It answers the question "what are we actually building?" and stops the team from inventing services that already exist or "folding in" things that should stay separate.

The inventory is grouped by category (application monorepo, edge services, shared packages, managed externals, reference-only prior art). Each entry carries a **status**:

- **build** — in scope, we're constructing this in this project.
- **external** — managed elsewhere (third-party SaaS, another team's service). We integrate with it but don't own it.
- **reference** — prior art we read or copy patterns from but do not deploy.

Do **not** mark items as "retired", "deprecated", or "previously planned" — if it's not being built or used, omit it. (See the greenfield doctrine.) The inventory describes the steady state, not the history of how the steady state was arrived at.

When scope changes (a service moves from "build" to "external", a non-goal flips to a build, a planned component gets dropped), update this file immediately and run a semantic sweep across plan docs.

---

## A. Application monorepo

| Name | Status | Notes |
|---|---|---|
| (example: `apps/gateway`) | build | (one-line role) |
| (example: `apps/web`) | build | (one-line role) |

## B. Edge services

| Name | Status | Notes |
|---|---|---|

## C. Shared packages

| Name | Status | Notes |
|---|---|---|

## D. Managed externals

| Name | Status | Notes |
|---|---|---|
| (example: Temporal Cloud) | external | (one-line — what we use it for) |

## E. Reference / prior art

| Name | Status | Notes |
|---|---|---|
| (example: `~/dev/vibe/foo-poc`) | reference | (what pattern we borrow from it) |
