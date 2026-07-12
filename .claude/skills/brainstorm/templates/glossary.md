# Glossary

This file collects **terms with project-specific meaning** — words whose definition in this project diverges from their general industry sense, or whose meaning is short and opaque enough that re-explaining it across docs wastes time.

The glossary exists to prevent the quietest and most expensive kind of design drift: two collaborators using the same word for different things. By the time you notice — usually mid-implementation — the cost of resolving the ambiguity is much higher than the cost of writing the entry that would have prevented it. So when you catch yourself saying "by X I mean…" for the second time, add the entry.

Do **not** catalog every term. Add to the glossary only when:
- A term has been used to mean two different things in the same session.
- A term's meaning here diverges from the standard industry sense (e.g., `subscriber` meaning a webhook destination rather than a pub/sub consumer).
- A short term names a specific concept that would otherwise need re-defining across docs (e.g., a node category name, an internal product term).

Entries are intentionally terse: one term, one line of meaning. Long explanations belong in plan docs or `decisions.md`.

---

| Term | Meaning |
|---|---|
| (example: `studio`) | the canonical task queue for non-publish work — see `04-runtime.md` |
| (example: `subscriber`) | a webhook destination registered against an event kind, distinct from a `webhook` which is the inbound side |
