# Runnable increments

Choose slices that exercise a complete path: user/input, processing, state or
storage, result, and relevant failure recovery. Building every model, then every
API, then every screen delays integration feedback until too late.

Begin with a representative path that exposes the highest relevant uncertainty.
After it works, extend cases while keeping the system understandable and
verifiable. A slice may span several files; file count is not a quality metric.

Explain when architectural refactoring, data model changes, visual replacement
and business behavior must happen together. Otherwise keep them distinguishable
so failures can be attributed. Reuse working project test/build tools instead of
constructing a new delivery platform.

For a migration or parity-sensitive refactor, establish representative old
behavior before replacing it. Compare responses, state and relevant performance
under the same input. Document deliberate behavior changes and known old defects.
Where output is nondeterministic, run the same version against itself to discover
natural noise before attributing differences to the new implementation.

For performance work record the baseline, hypothesis, changed variable and
measurement conditions. Preserve behavioral constraints and reject apparent gains
caused by skipping work. Repeated measurements distinguish noise from benefit.
Stop when the stated target is met or further work is outside the agreed scope.

Record actual slice progress and the next useful action in the Spec. A task list
being checked off is not evidence that the assembled feature works. Slicing does
not impose branch creation, session coordination or serial execution on users.
