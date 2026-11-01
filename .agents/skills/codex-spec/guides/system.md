# Relevant system model

Read enough source to explain the affected behavior and choose the right layer.
Follow definitions, references, types and existing analogous code. A repository
map is a starting point, not proof of architecture. Avoid a whole-repository
reading requirement or architecture document for a local change.

For stateful or cross-module work establish the relevant facts:
- State owner and source of truth; distinguish stored and derived values.
- Entry points, data flow, contracts and callers.
- Invariants that must remain true and where they are enforced.
- Upstream/downstream effects, compatibility and real failure conditions.
- Existing components or services to extend rather than duplicate.

For asynchronous behavior consider actual transitions: start, success, failure,
cancel, retry and re-entry. Ask what happens if an older request returns after a
newer one, a component unmounts, or a user repeats an operation. Keep cancellation
and cleanup meaningful rather than merely hiding the UI result.

Example: a search page starts A then B. If A completes last, the results must
still correspond to B. A test should control completion order; a timeout-based
sleep does not reliably establish the race. Determine where request identity or
cancellation belongs in the existing state architecture.

When adding a field or changing an API, trace producers, serialization, clients,
state consumers and display. Check values, optionality, units, error shapes and
versioned APIs across the whole relevant path. A locally correct function can
still break its caller. Reuse the project's centralized error and request layer.

Choose the smallest correct implementation. Add abstractions only when they
serve a real repeated responsibility. Keep stable invariants close to source;
re-check implementation details against the current files and runtime.
