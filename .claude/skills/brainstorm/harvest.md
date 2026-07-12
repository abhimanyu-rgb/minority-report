# Harvest adapter

Harvest is **optional and offered, never assumed**. By default the session folder is the product: a self-contained registry the next `/brainstorm start` resumes from. Run this adapter only when (a) the repo is v9-harnessed — `docs/architecture/` and `docs/modules/` exist — and (b) the user accepts the offer at `stop`.

## Routing

The harvest is a structured diff between the session pillars and the live docs, routed by scope: module-local findings → `docs/modules/{m}/pillars/`, cross-module → `docs/architecture/`, IA/contract changes → `docs/boundaries/` (via the `boundary` skill), backlog → `docs/history/`.

| Session source | Destination |
|---|---|
| `thesis.md` narrative | `docs/history/plans/YYYY-MM-DD-{slug}.md` (Status: Draft, `documentation` skill §8 Plan template) |
| `domain-model.md` | `docs/architecture/domain-model.md`; if it changes the IA or a cross-cutting contract, **flag for the `boundary` skill (`create`)** — don't hand-write boundary files |
| Decisions spanning 2+ modules | one ADR per cohesive theme → `docs/architecture/adr/ADR-NNN-{slug}.md`, authored to the **`documentation` skill §10 ADR template** (frontmatter `status:` is the lifecycle source of truth — no body Status line; required sections Decision/Context/Consequences); rejected alternatives → the ADR's **Options Considered** table |
| Module-local decisions / doctrine / glossary / rejected | `docs/modules/{m}/pillars/{decisions,doctrine,glossary,rejected}.md` |
| Cross-module doctrine / glossary | `docs/architecture/domain-model.md` / `docs/architecture/glossary.md` |
| `tech.md` deviations | `docs/architecture/references.md` or the relevant ADR |
| `non-goals.md` / `references.md` | `docs/architecture/{non-goals,references}.md` |
| `backlog.md` | `docs/history/backlog.md` (P0–P3) |
| Still-open questions | `docs/architecture/open-questions.md`, each with a *Resolution lands in* pointer |
| `build.md` (brownfield/hybrid: migration strategy, gotchas, rollout) | the plan doc in `docs/history/plans/` — execution content is plan content, not architecture |

Append a changelog entry at `docs/history/changelog/YYYY-MM-DD-brainstorm-harvest-{slug}.md` listing what was written where.

## After harvest

Offer to delete the session folder (the dispersed homes now carry the content; the next session primes from them by copying relevant docs into `basis/`). Default to **keep** if the user is unsure — a kept folder simply resumes.
