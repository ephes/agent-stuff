# Handoff propagation repair

Expected the existing canonical value-driven policy to govern generated handoffs.
Inspection found all three review generators still preferred a clean second
review; implementation generators made review expectations conditional on target
repo guidance despite a blanket reviewer-command ban. Fresh/resumed prompts could
therefore lose repair containment, advisory disposition, or review ownership.

The generators now explicitly carry canonical behavior, cumulative unresolved
findings, repair baselines and driver/worker roles. The canonical Pi model and
compact Codex goal handoff preserve `openai-codex/gpt-6-sol`; the incompatible
existing Pi harness is a documented blocked gate, not silently migrated. The
synthetic requests beside this file exercise decision boundaries without private
project or session data. The shared review-cycle log was deliberately untouched.

Promotion: promoted — implement-handoff / handoff-impl, Review ownership in
generated handoffs; review-handoff / handoff-review, Review behavior to carry
into every prompt. Canonical stopping policy itself remains unchanged.
