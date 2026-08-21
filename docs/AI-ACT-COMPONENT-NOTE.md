# EU AI Act component note

Decision Clicker does not contain, train, call, or distribute an AI model. It
records a human user's explicit choices in a local file-based governance
system. Recommendation text, when present in a decision record, is input data;
Decision Clicker does not generate or rank it.

The component therefore does not independently perform an AI-system function.
If an AI-enabled application integrates the `DecisionClicker` facade, that
application's provider or deployer remains responsible for classifying the
combined use case, documenting generated recommendations, and preserving
meaningful human control. The integration must not convert a model prediction
into a recorded user decision without an explicit user action.

This is a technical component statement, not legal advice. Classification
must be reassessed if model inference, automated ranking, or autonomous choice
is added later.
