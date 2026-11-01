# Proportionate, credible verification

Choose checks from the behavior and risk, not a fixed quota. Reuse appropriate
unit, component, contract, integration, real-app and performance checks. Small
reversible changes do not need a new permanent test suite or every repository
test. Broaden after new failures or unresolved risks, not just to prolong work.

Verify through the relevant public entry point and inspect the final state.
For each important assertion ask whether the check would fail if the feature
were broken. For a regression, reproduce before the fix and rerun under the same
conditions after it. A controlled mutant or reverting the fix in a disposable
fixture can test a crucial assertion; use this selectively, not on every edit.

Examples of weak verification:
- Clicking Save without checking persisted data.
- A screenshot used to claim cancellation works.
- An async test that never returns requests out of order.
- A UI test whose expected state was already true before the action.
- Replacing the affected real integration with a mock, then claiming parity.
- Reading a green CI summary without checking a failed underlying command.

Check meaningful action transitions before and after the action. Explain why
fixtures and stubs represent reachable states and which integration they omit.
Do not change assertions, skip paths or relax thresholds simply to obtain green.
If the requirement legitimately changes, update its checks explicitly.

Keep conclusions distinct: test-confirmed, source-supported, disproved, and
unverified. Record actual command/target, result, relevant source or build and
evidence location. Re-check affected evidence after related changes; unrelated
changes do not automatically require a full rerun. Tools can be run directly;
there is no required receipt format or execution wrapper.

Report implementation, runtime verification and actual human feedback separately.
A passing test covers its inputs, environment and assertions; it is not proof of
production correctness. Missing runtime capability is a stated limitation.
Hand off useful completed work with remaining unknowns without inventing success.
