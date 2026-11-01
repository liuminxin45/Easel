# Design inheritance and real interaction

Inspect the current interface before broad changes. Find the project's component
library, design tokens, neighboring screens, interaction conventions and any
user-provided design or screenshot. A reference should explain which properties
to preserve; it need not prescribe every pixel.

Prefer existing controls and patterns. Record a justified exception when adding
a new pattern. If existing design is part of the problem, propose a coherent
change across the affected surfaces instead of preserving a defect by habit.
Check component documentation and installed versions before copying API usage.

For material UI work answer the relevant questions:
- Which existing component, layout and token supplies each major element?
- What is the primary action and can the intended user find it?
- What does loading, empty, error, disabled and success look like?
- How do cancel, retry, back and re-entry behave?
- What changes on narrow screens, keyboard navigation and reduced motion?

A screenshot plus layout and state notes is often more useful than a screenshot
alone. For a new visual direction implement one representative page or
interaction first, inspect it, then extend it. Avoid inventing a separate design
system for each feature. Keep explanatory copy useful to the product's users.

Verify in the actual app and target viewport where available. Capture relevant
before/after states and exercise the user path. Inspect DOM, computed styles and
box metrics when a layout fix fails, rather than guessing another CSS patch.
Check whether clicks actually change state; a still image cannot prove this.

Review against coherent design, craft and usability criteria calibrated with
project examples and user feedback. "Could it be prettier?" produces endless
opinions. Report a concrete mismatch and impact. Preserve a better intermediate
version when further changes worsen the result; a higher self-score is not proof.
