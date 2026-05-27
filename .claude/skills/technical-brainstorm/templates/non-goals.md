# Non-goals

This file is the **explicit list of things we are not building** in the current scope, with the reason for each. It is the mirror of `inventory.md`: where inventory says "this is in scope", non-goals say "this looked plausible but is deliberately out".

Non-goals carry real weight. Every entry here is a constraint that future decisions should respect — a scope-creep guard. The reason field is load-bearing: without it, a non-goal looks like an arbitrary "no" that future-you will second-guess at the first complication. With the reason, future-you knows whether the non-goal still holds when circumstances change.

Each non-goal should include a **Re-evaluate when** clause where applicable. Non-goals are not permanent vows; they are scope decisions tied to current constraints. When the constraint changes (a customer signs in a new region, a competitor ships the feature, infrastructure costs drop), the non-goal may move into scope. The re-evaluate clause names the trigger so the team doesn't carry a stale non-goal forever.

At milestone boundaries, scan this file. If a non-goal's re-evaluate trigger has fired, move the item to `inventory.md` with status `build` and delete the non-goal entry here — do not strikethrough, do not leave a "(promoted)" marker.

---

- **No multi-region writes in M0.**
  *Reason:* cost > benefit until 3+ paying customers in distinct regions.
  *Re-evaluate when:* second paying customer signs in a non-primary region.

- **No mobile app.**
  *Reason:* product hypothesis is desktop-first; no validated mobile demand.
  *Re-evaluate when:* >20% of dashboard sessions are mobile UA.

- (add more here)
