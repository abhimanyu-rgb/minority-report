# Greenfield writing doctrine

> **The reader has no past.** They've never seen an earlier version of the system, never heard of the alternative you considered, never knew about the repo you were going to fold in. Write for them.

For projects with nothing built yet — no production deploys, no users, no legacy code — architecture docs describe the system as it **will be**, in present tense. The temptation to narrate the design journey ("we considered X, chose Y, dropped Z") produces documents full of phantoms — references to things the reader has no way to imagine.

These rules apply equally to the first draft and to subsequent edits. After every design decision, the architecture doc should look as though the chosen option was always the plan.

---

## The rule

Describe what the system **is** (or will be — same thing in greenfield). Never describe what it isn't, used to be, replaces, supersedes, or is migrating from.

There is no past tense in a doc for software that doesn't exist yet.

---

## Banned patterns

| Don't write | Why it's wrong | Write instead |
|---|---|---|
| "X replaces Y" / "X supersedes Y" | Reader doesn't know Y. | "X is the [role]." |
| "Previously planned" / "originally proposed" / "we used to" | There is no previous. | Describe the current plan. |
| "What was dropped" / "What we ruled out" sections | Only useful when readers carry a stale model. | Move reasoning to `decisions.md` if load-bearing; otherwise delete. |
| `~~strike-through~~` text | Tracks edits for live readers; pollutes fresh docs. | Delete the struck text. Keep the surviving prose. |
| "ex-Foo", "from ex-Bar" annotations on packages | Repo-fold bookkeeping. | Just name the package. |
| "Folded into monorepo" / `import-legacy.sh` / migration scripts | Migration mechanic, not architecture. | Describe the monorepo as the steady state. |
| "v1 vs v2" / "future migration target" | Implies one is becoming the other. | Describe v1. Phase-2 ideas can be a "future scope" subsection without "migration" framing. |
| "(existing — `~/dev/foo`)" / "no build needed" markers | Differentiates from non-existing; in greenfield everything is to-build. | Just list the service. |
| "There is no foo_table" / "we don't have a foo service" | Reader didn't expect one. | Don't mention it. |
| "Per Decision-N resolution" inline citations on every paragraph | Architecture doc isn't a decision log. | Plain prose. One cross-ref per section, only when the *why* is non-obvious. |
| "Resolved (was: open question)" / "(retired)" markers | Edit-history bookkeeping. | Delete — the resolution **is** the doc now. |
| "What this kills" / "Trade-off accepted" headings | Decision-capture format leaking into architecture. | Keep these in `decisions.md` only. |
| "We no longer X" / "X is no longer needed" | Reader had no expectation that X existed. | Don't mention X. |
| "Renamed from foo to bar" / "(formerly known as …)" | The rename doesn't matter — only the current name does. | Use the current name. |

---

## Smell-words grep

`stop` runs this automatically. Manual invocation:

```sh
grep -rEni \
  'replaces|supersedes|superseded|previously|formerly|originally proposed|what was dropped|fully retired|~~|ex-[a-z-]+|folded in|import-legacy|migration target|migrate from|no longer|we used to|resolved per|renamed from|formerly known' \
  plan/
```

In a clean greenfield architecture doc, this should return no hits in `01–NN` numbered docs.

Hits **are** acceptable in:
- `decisions.md` — scoped to a specific decision-capture entry.
- `rejected.md` — scoped to a rejected alternative.
- `references.md` — describing external prior art.
- Commit messages and PR descriptions.
- `./plan/sources/` — copies of input documents (not authored under these rules).

---

## Where the past DOES belong

- `decisions.md` — alternatives + why the chosen option won, **only** when the reasoning isn't obvious from the architecture itself.
- `rejected.md` — paths considered and rejected.
- `references.md` — external prior art.
- Commit messages, PR descriptions — what changed and why; lives in git, not docs.

These are the only four places. Architecture docs (`01-foo.md`, `02-bar.md`, ...) are present-tense.

---

## What's still allowed (don't over-correct)

- **Forward planning that names a phase** ("ships in M7 so the bus already knows about `lead.created` when CRM sync arrives") — describes a positive future, not a past.
- **Constraint statements** ("we accept a 5-second tile lag for predictable server load") — current tradeoffs, stated as facts. Live in `decisions.md`, not architecture.
- **Cross-refs** ("see `04 §4.3`") — pointers, not history.
- **Negative assertions about external systems** ("the upstream service has no native fan-in") — describing a real third-party limitation is fine.
- **Future-scope subsections** ("Phase 2 considerations") — labelled clearly, not framed as migrations.

---

## Before merging an architecture doc, ask

1. If a brand-new collaborator read this section cold, would they need to know about the alternative I'm comparing to? If no, delete the comparison.
2. Does the section read as present-tense description, or as a story of "we went from X to Y"? Rewrite the story form.
3. Are there strike-throughs? Delete them.
4. Does an open-questions list still contain resolved items? Move them to `decisions.md` and drop from the list.
5. Are there inline "(per Decision-X)" citations sprinkled through the prose? Strip — keep at most one cross-ref per section.

---

## Why this matters

A greenfield doc that reads like a migration guide signals two things to a new reader:

1. **There is hidden context I don't have.** Every "previously" / "replaces" makes them wonder what they're missing.
2. **The author is still in the middle of deciding.** Strike-throughs and "(resolved)" markers feel provisional.

Both undermine the doc's authority. A clean greenfield doc reads as an act of architecture, not an act of revision.
