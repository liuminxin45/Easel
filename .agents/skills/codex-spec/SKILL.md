---
name: codex-spec
description: "Develop, refactor, diagnose and verify software changes with product intent, relevant system context and evidence. Use in Codex Spec projects; supports independent specs and concurrent conversations in the current checkout."
---

# Codex Spec

Use engineering judgment to deliver the user's outcome. This Skill adds guidance
and project knowledge to Codex's normal tools. It does not control execution.

## Four engineering habits

- Before changing code, establish the outcome, reference, preserved behavior and
  consequential unknowns. Separate user decisions from your assumptions. Use a
  representative prototype when seeing behavior will clarify the requirement.
- Understand the relevant system: state ownership, data flow, contracts, callers
  and downstream effects. Find existing implementations before adding another.
  Read enough to explain the change; broad repository reading is not a goal.
- Verify observable behavior through the appropriate real entry point. Match
  checks to risk, inspect actual results and state what remains unverified.
  A screenshot proves appearance; a successful command proves only its checks.
- When a fix fails, compare the expected and observed result, identify which
  hypothesis weakened, then gather evidence that distinguishes remaining causes.
  More patches without new facts are not progress.

## Working on a request

Respect whether the user requested discussion, review or implementation. Continue
authorized work without repeatedly asking permission. Ask about consequential
ambiguity; continue independent work while a required decision remains pending.

Read this project's AGENTS and relevant project facts. Discover the small guide
catalog in [guides/index.json](guides/index.json); load only relevant guide bodies:

| Situation | Guidance |
| --- | --- |
| Product goal or acceptance ambiguity | [product](guides/product.md) |
| UI, UX, copy or visual consistency | [ui](guides/ui.md) |
| State, async behavior or cross-module contracts | [system](guides/system.md) |
| Large feature, refactor or migration | [slices](guides/slices.md) |
| Unknown cause or unsuccessful repair | [diagnosis](guides/diagnosis.md) |
| Choosing checks or evaluating results | [verification](guides/verification.md) |
| Project context, continuity or reusable lessons | [knowledge](guides/knowledge.md) |

Use `codex-spec context --json` if installed to list project knowledge metadata.
Select relevant resources explicitly, or read their referenced files directly.
Check knowledge against current code and runtime facts; report stale guidance.
Tool descriptors are documentation, not proof that a tool is available.

Use or update the relevant `specs/<id>/spec.md` for a durable feature goal. A small
fix can update an existing Spec; no new document is required just to satisfy a
process. [The template](assets/spec.md) is a menu of useful sections, not a form.
Keep intent, decisions, current progress and evidence together; split details
only when the record becomes difficult to use. Do not copy complete transcripts.

Choose a small verifiable implementation. Keep design, behavior and structural
changes understandable. Stop expanding scope when the outcome and appropriate
checks are satisfied; record independent improvements as follow-up candidates.

## Checkout and delivery

Work in the current checkout and branch. Multiple Specs and Codex conversations
can work concurrently. There is no branch creation requirement, dirty-tree gate,
file-ownership protocol, session lock, active-Spec singleton or central scheduler.
Re-read current files before subsequent edits; remembered state may be outdated.

Use ordinary tools directly. No CLI runner, receipt import, fixed stage order,
mandatory new tests, full-suite run, independent verifier or multi-agent setup is
required. Existing project requirements and the user's authorized scope apply.

When a commit is requested, follow the project's commit style and include:

```text
Spec: <one or more spec IDs>
Spec-Docs: <paths to the relevant spec documents>
```

Do not invent a Spec reference or acceptance. Report the actual outcome, meaningful
verification, evidence locations and remaining limitations. Distinguish completed
implementation, runtime verification and human feedback. Missing runtime access
limits the claim; it need not prevent delivering useful verified work.
