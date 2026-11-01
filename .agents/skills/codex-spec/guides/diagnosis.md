# Evidence-driven diagnosis

Establish a factual starting point: symptom, affected target/version, time or
request, reproduction, observed state and recent changes. Separate logs and
measurements from a user's account and from your static deductions. Avoid
combining observations from different instances or times into one imagined event.

Cross-check the relevant evidence sources:
- Project facts explain domain semantics, repository mapping and invariants.
- Current source and call relationships explain possible behavior.
- Runtime logs, traces, requests and state establish what actually happened.
- History helps locate changes but does not establish causality by itself.

Keep log windows, pagination and truncation explicit. Query the actual target;
an empty tool response is not proof that no event occurred. Disclose unavailable
tools and degraded investigation methods where they limit the conclusion.

For each serious candidate capture trigger, path, predicted state change,
supporting evidence, conflicting evidence and a way to falsify it. Prefer an
experiment that distinguishes two explanations over a speculative repair.

If a repair fails, update this short record before another substantial patch:

| Hypothesis | Expected change | Actual observation | Conclusion | Next discriminating check |
| --- | --- | --- | --- | --- |
| Late response replaces current search | Ignore stale completion | Symptom remains with one request | Race does not explain this reproduction | Inspect shared cached state |

Do not repeat a patch with new wording when there are no new facts. Check
environment, reproduction and acceptance as well as implementation. Retries and
fallbacks can be useful mitigation; state the remaining failure mechanism.

Prefer existing centralized handling and the actual failing entry point. Do not
add unrelated defenses or abstractions to every caller. Independent reviewers
can suggest hypotheses, but agreement or majority vote does not establish truth.
Escalate a concrete missing decision or capability when independent progress is
exhausted; there is no universal retry count or forced investigation stage.
