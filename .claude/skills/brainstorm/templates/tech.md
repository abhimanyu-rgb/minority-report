# Tech

This file holds the **technology choices** for the idea. It is seeded at bootstrap from the harness's opinionated stack (e.g. `.claude/rules/general.md` recommended-packages table) when one exists — those rows arrive as defaults, not decisions.

Its job afterward is to be a **lens**: when a conversation move conflicts with a row here, the sync (or the skill, in the moment) surfaces it — *"you just proposed local component stores; the stack says Redux Toolkit — deviating or steering back?"* A confirmed deviation gets recorded below with its why; an unconfirmed conflict becomes an open question.

## Stack

| Layer | Choice | Source |
|---|---|---|
| [e.g. UI] | [react ^19] | harness default |
| [e.g. state] | [@reduxjs/toolkit] | harness default |
| [layer] | [choice] | decided this session — D[n] |

## Deviations

Each deviation from a harness default carries a why:

### [Choice] instead of [default]

**Why.** [Constraint, requirement, or incident that justifies the deviation.]

**Scope.** [Whole project, or only a named module/surface.]
