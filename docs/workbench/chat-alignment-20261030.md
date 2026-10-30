# ChatPage alignment — 2026-10-30

Baseline: local official `upstream/main@5a597e5`. Native Codex execution,
RPC pooling and `_sessions` ownership remain upstream-owned. No new model
transport, global skill installation or permission auto-approval was added.

## Boundaries and behavior

- The private application owns one in-memory chat coordinator per client and
  session. Switching views preserves the stream, cursor (inside upstream
  `streamChat`) and answered-question set. Refresh uses GET replay of the same
  turn. Authentication generation changes dispose readers and private memory,
  retaining input drafts and operation identity.
- Permission answers now return the upstream `ok/status/expired/error` shape,
  retaining the legacy `answered` alias. Answers and status probes carry exact
  session/turn identity. The existing turn receipt records question lifecycle;
  answered, expired and stopped questions emit `question_closed`. No second
  approval queue exists. Lost acknowledgements query status without resubmission.
- The upstream deterministic title helper supplies optional `initial_title`
  metadata, applied atomically on the first accepted turn. Explicit renames
  win. Opening an untouched historical placeholder repairs it through the
  revision-protected `auto-title` session action; old manual operation receipts
  conservatively prevent repair. Turn messages and frozen prompts are unchanged.
- Live activity shows the latest step; complete history stays in the receipt.
  The upstream message component folds execution steps only after completion.
  Textarea sizing also follows the empty/history layout transition, preserving
  long drafts and internal scrolling across refresh.
- The shared brush accepts an optional generic capability catalog. Private data
  comes from the existing project skill API; slash and brush select the same
  versioned action. Brush selection prefills without sending. Plus uploads
  material; Enter/Shift+Enter and IME behavior remain upstream-owned.
- The upstream gallery accepts structured registered artifacts and optional
  original-download URLs; ordinary text files use its download fallback.
  Raw model paths do not become authorized files. The private message extension
  only exposes the exact product-page link and delivery issues. Parameters,
  adoption, feedback and delivery authorization stay on the product page.
- Ordinary conversational retry creates an explicit new turn pinned to the
  original skill version (`skill_refs` metadata on the existing receipt API).
  Production recovery remains on the product page; unknown receipts never replay.

The shared changes are optional generic ports in ChatPage, BrushEntry,
QuestionCards, MessageBubble, ArtifactGallery and their existing API/artifact
types. These components have no imports from private business modules. The
original App entry and private entry both build independently with Node 24.19.0.

## Evidence

Immutable pair:

- Backend `workbench-20261030-061429`, manifest
  `c718714d667b5f2ee05d4cfa7b835b265de341bda4b276f7bffc3b7313f43125`.
- Frontend `native-easel-workbench-20261030061308`, manifest
  `b535be4d12ccb04a63c41bf73c949b8daf1522fe8497998b9f863fb4ebf6c8f3`.

Evidence is under `.local/workbench-validation/chat-alignment/`:

- 183 frontend tests; 111 chat/architecture/skill checks; 68 permission and native
  ownership checks; 19 upstream event/question replay checks in the upstream
  Python environment. A separate 94-test business/completion/correction/deployment
  regression run passed during implementation (overlaps the above suites).
- Frozen-pair Edge acceptance: 27 business checks, 14 permission/lifecycle checks,
  eight online-upgrade/offline-draft checks. Loaded backend module paths and
  candidate member hashes were verified. Windows Edge ran both headless and
  visible; Android layout/input is browser simulation, not physical vivo evidence.
- TEMP execution produced poster and article files, preserved raw feedback,
  modified exact parent versions and exercised unknown receipts. No real model,
  publishing action or system PowerShell command was executed by acceptance.
- The extra Windows native-input check was stopped by Computer Use's automatic
  URL-policy check. It is not counted as passed. Edge browser automation passed;
  no alternate tool was used to perform the blocked native-input action.

Activation uses the existing admission fence, idle/queue checks and immutable
pair switch. The same authoritative database remains in place. Previous release
assets, historical turns, frozen inputs and unknown operations are preserved.

The final follow-up clears transient connection notices when streaming resumes
or a terminal receipt is verified. It was built from commit `9e57c7d` plus that
single private UI change in an isolated source tree. Its backend members are
byte-identical to the previously validated runtime. Concurrent collection,
account and cache edits in the working checkout were excluded from this release;
those files were preserved. Reports for this pair use the `isolated-*` prefix.
