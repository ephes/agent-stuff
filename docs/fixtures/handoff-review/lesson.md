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

Superseded 2026-10-05: the `gpt-6-sol` Pi instruction came from a global agent
file written on 2026-09-23, before both harnesses were pinned to `gpt-6.1-sol`
on 2026-09-30, so it was stale rather than newer. Canonical policy and handoffs
now match the harness (`openai-codex/gpt-6.1-sol`); the remaining Pi blocker is
the expired OpenAI Codex login. Lesson: compare dates before treating a
conflicting instruction as the current one.
