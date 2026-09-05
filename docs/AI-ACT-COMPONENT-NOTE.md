# EU AI Act component note

Decision Clicker does not contain, train, call, or distribute an AI model. It
records a human user's explicit choices in a local file-based governance
system. Recommendation text, when present in a decision record, is input data;
Decision Clicker does not generate or rank it.

The component therefore does not independently perform an AI-system function.
AI-enabled, memory, and policy integrations must use the proposal-only
`ProposalSubmitter` facade. It can add an open candidate but exposes no decide,
implementation-status, intake, or undo operation. The JSON boundary enforces
the same rule. A human-facing adapter may use `DecisionClicker.decide` and
`DecisionClicker.undo` only as the direct consequence of an explicit visible
user action. The bundled HTML forms are the reference boundary: each mutation
needs a short-lived, single-use capability bound to its action and record, and
the result shows an immediate confirmation with an undo control.

The integrating application's provider or deployer remains responsible for
classifying the combined use case, documenting generated recommendations, and
preserving meaningful human control. Evidence anchors and context fingerprints
are provenance locators, not truth or correctness assertions.

This is a technical component statement, not legal advice. Classification
must be reassessed if model inference, automated ranking, or autonomous choice
is added later.
