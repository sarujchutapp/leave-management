# Optimizer plans against free days; the validator gates on approved-only

The Leave Optimizer (`/advance`) suggests breaks against an employee's *free*
vacation days — `available − (all pending + approved vacation days, half-days
counted as 0.5)` — and treats pending/approved half-day dates as blocked-but-
present (they block a suggested booking but don't fill a continuous-absence
run). `validate_request`, the hard gate at submit time, deliberately stays
**approved-only** for the balance check.

The two differ on purpose. The optimizer is advisory, so it is conservative:
anything in flight is already spent, and it should never suggest a break that
can't coexist with what you've already booked or requested. The validator is the
authoritative ledger and must not block a request on quota a pending (possibly-
to-be-declined) request hasn't actually consumed. Collapsing the asymmetry to
"make them consistent" reintroduces the over-suggestion bug: with a pending
request in flight, an approved-only optimizer would propose a second break that
blows the yearly quota once both approve — and the approved-only validator
wouldn't catch it either.

Net effect: after this change the optimizer's accepted set is a strict subset of
the validator's, so every suggested break still passes `validate_request`.
