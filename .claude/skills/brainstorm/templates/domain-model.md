# Domain model

This file holds the **information architecture** of the idea: entities, relationships, cardinalities, and who owns what state. This is where facts like "an account has many leads" land the moment they're said — they are neither principles (`doctrine.md`) nor terms (`glossary.md`), and they must not be lost to the transcript.

The loop's *abstract* step feeds this file: when the user implies structure without naming it, propose the entry here.

## Entities

### [Entity]

[One paragraph: what it is, what state it owns, where it lives (client / server / external system).]

## Relationships

| From | To | Cardinality | Notes |
|---|---|---|---|
| Account | Lead | 1 : N | [e.g. leads cannot transfer between accounts — see D3] |

Cardinality changes are design changes — when one shifts, expect the sync to raise questions against routing, storage, and milestones.

## Invariants

Rules the model must always satisfy, stated as present-tense facts:

- [e.g. Every lead belongs to exactly one account at any point in time.]
