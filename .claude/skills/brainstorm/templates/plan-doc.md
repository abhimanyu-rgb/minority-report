# NN — [Domain name]

> This is a **plan doc**, not a pillar. It describes one domain of the system (e.g., runtime, storage, ingress) in present tense, as if the chosen design were always the plan. Plan docs do not host their own "open questions" sections — those live in `pillars/questions.md`. Plan docs do not narrate the design journey — that lives in `pillars/decisions.md` and `pillars/rejected.md`. Plan docs describe what the system is.
>
> Number plan docs sequentially: `01-foo.md`, `02-bar.md`, ... Each plan doc owns one domain. If a section grows past ~500 lines, split it into two plan docs rather than letting it sprawl.
>
> Cross-reference other plan docs with `see 04 §3.2` — pointer, not duplicated content.

---

## On versioning iterations

If this plan doc goes through a substantial rewrite (decision reversal, structural shift, ≥3 sections change together), preserve the evolution by saving a new version as `NN-domain-v0.X.md` rather than overwriting. Examples:

```
01-architecture-v0.1.md       ← initial draft
01-architecture-v0.2.md       ← second draft after architecture change
01-architecture-v0.3.md       ← current draft (the one to read)
```

Each version stays in the folder. Readers can follow v0.1 → v0.2 → v0.3 in order to see exactly how the design evolved. The current version's top-of-file frontmatter or first line notes its status:

```markdown
# 01 — Architecture (v0.3)

> **Status:** Current draft. Supersedes v0.1 and v0.2. v0.4 will narrow content.
```

Skip versioning for small edits (typos, single-section polish, find-and-replace). The versioning pattern is for substantial rewrites that warrant a separate readable artifact.

The `stop` step in the brainstorm offers to prune older versions if you want to simplify the final handoff. Keeping them preserves the design rationale across long sessions; pruning them produces a clean steady-state.

---

## 1. What this is

[One paragraph in present tense describing what this domain is, what it does, and who depends on it. No "we decided" framing, no comparisons to alternatives.]

## 2. Components

[Subsystems, services, or modules inside this domain. Each gets a subsection with: name, role, what it owns, what it depends on. Diagrams are OK if they help.]

## 3. Interfaces

[How other domains interact with this one. APIs, queues, events, file formats. Stable contracts only — speculative ones go in `pillars/questions.md`.]

## 4. Constraints accepted

[Tradeoffs that shape the design. Phrased as current fact: "we accept a 5-second lag for predictable throughput", not "we considered streaming but chose batch".]

## 5. Future scope (optional)

[Cleanly labelled phase-2 ideas. Not framed as migrations. Skip the section if there's nothing here.]

---

## Open questions for this domain

See [`pillars/questions.md`](./pillars/questions.md): Q-N, Q-M, ...

(One line, never more. The plan doc never hosts question bodies.)
