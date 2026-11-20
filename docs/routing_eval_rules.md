# Routing eval labelling rules
- Labels: renewal, health, finance, document, unknown. Only the agent is scored, not the action.
- Ambiguous and multi-intent: label = the agent for the first action requested.
- Adversarial: label = the agent the underlying request belongs to. This set measures routing, not safety; safety is enforced by the PolicyEngine and covered by pytest.
- Off-topic queries are labelled unknown.
- Labels were written by the author after seeing the keyword list. Labels are never changed after a router has been run.
