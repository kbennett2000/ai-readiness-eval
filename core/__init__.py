"""Eval harness: run a model against the tasks and score it deterministically.

Design and rationale are recorded in ADR-0004
(docs/adr/adr-0004-eval-harness-and-scoring.md). The two auditable cores are
`answer_block` (parse the model's structured answer) and `scorer` (compare it to
ground truth) — both are network-free and heavily tested.
"""
