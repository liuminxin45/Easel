# Small, source-backed project knowledge

Keep reusable project knowledge separate from current task state. Use references
to actual sources, not copied transcripts. The optional CLI lists metadata first:

```text
codex-spec context --json
codex-spec context --select guide/system --json
codex-spec context --select team/project::map --detail overview --json
```

Project packs are local directories containing `pack.json` and user-maintained
resources. See the project's knowledge documentation for the format. Classify
facts, procedures, design references, constraints and experiences explicitly.
Use summaries for relevance, optional overviews for navigation, and original
files for detail. Candidates are not automatically instructions or verified facts.

Store stable architecture, domain terms, important invariants, component sources
and verified run/debug methods. For reusable experience include symptom, scope,
evidence, explanation, resolution and remaining limits. A single successful run
does not establish a universal rule. No durable knowledge is inferred merely
from filenames, and no project-specific pack ships in Codex Spec.

Review knowledge when current source or runtime conflicts with it. Keep source
references, review dates and applicable versions when useful. Changes may make
knowledge outdated; neither a TTL nor a confident summary establishes truth.
If ordinary indexed files suffice, do not introduce a vector database or service.

For continuation keep a short current section in the relevant Spec:
- User outcome and preserved behavior.
- Confirmed decisions versus assumptions.
- Actual progress, latest meaningful evidence and unfinished conditions.
- Failed hypotheses and next action.

On resumption read it, inspect relevant current files and verify the actual
environment. Do not reconstruct user intent from git diff alone. Keep original
evidence available behind concise summaries. The user's later changes take
precedence over remembered state. This record is not a global active-task lock.
