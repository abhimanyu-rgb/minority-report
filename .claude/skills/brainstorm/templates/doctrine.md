# Doctrine

This file holds **stable principles that pre-answer future questions**. When a new question arises during a brainstorm, check here first — the doctrine may already settle it without a full debate.

Doctrine entries should be **rare and durable**. They are not preferences ("I like Postgres") and not one-off picks ("we picked Temporal for this project"). They are statements that apply across many decisions: *"we never self-host stateful services in M0–M3 because operating burden outweighs cost savings at our scale."* A doctrine that gets revised every other week isn't doctrine — it's a preference in disguise. Demote it to `decisions.md`.

Add to doctrine only when a principle has either (a) been validated across multiple decisions in this project or others, or (b) is imposed from outside (compliance, vendor lock-in, team size) and won't change without a major shift. Doctrine pre-empts argument; if you're not confident the principle will hold for the next six months, don't write it here.

Each entry carries **Principle** (the one-line statement), **Why** (the reason this is principle, not preference — often a past incident, a hard constraint, or an accepted tradeoff), and **Applies when** (the triggers, so a reader recognizes "ah, this is a doctrine question" rather than re-debating from scratch). An optional **Exceptions** field is allowed but suspicious — if a principle has many exceptions, it's mis-stated.

Examples of real doctrine entries from past projects: *"Temporal IS the trace — no separate APM tool."* — *"No Terraform; deploys are wrangler + GitHub Actions only."* — *"Secrets only via wrangler, never in code or env files."* — *"Buy-not-build for non-core capabilities until paying-customer signal justifies otherwise."*

---

## P1 — [Principle name]

**Principle.** [One-line statement of the rule.]

**Why.** [The reason this is a principle, not a preference. Often a past incident, a hard constraint, or a tradeoff the team has already accepted.]

**Applies when.** [Triggers — situations where this principle should be invoked.]

**Exceptions.** [Optional. Cases where the principle deliberately does not apply. If you find yourself listing many exceptions, the principle is probably mis-stated.]

---

## P2 — [Principle name]

(same format)

---
