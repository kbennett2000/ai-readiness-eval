"""Answer contracts: what a pack's cohort is asked, and how the answer is scored (ADR-0044).

Until this module existed there was exactly one answer contract, and every part of it was a module
constant — `scorer.DIMENSIONS`, `prompt.ANSWER_BLOCK_SUFFIX`, `answer_block.parse`. That was correct
while every measured pack was an API surface. It stopped being correct the moment a cohort arrived
whose ground truth is discrete engineering values published as manuals: not one of the six API
dimensions applies to it, so re-interpreting them would have meant scoring a `method` column on a
surface with no methods.

A `Pack` declares `cohort:` (default `api`) and everything contract-shaped is read from here.

THE API CONTRACT IS ASSEMBLED BY REFERENCE, NOT REWRITTEN. Every callable below is the same function
object the code has always called, imported from the same module. That is deliberate and it is what
makes the split auditable: the API path cannot have changed behaviour, because there is no new API
code to have changed it. The proof obligations are stated in ADR-0044 and discharged in the same
commit — the frozen regression gate is unmoved and every committed `scores.json` in the cohort is
byte-identical.

WHAT A CONTRACT DOES NOT GET TO DECIDE. The condition registry, the sterile invocation, the archive
format, the tool-discipline assertions, the resumable runner and the report writer are all shared,
and a contract cannot reach them. It supplies a question, a parser, a dimension set and a scoring
rule; everything about how a run is made and recorded stays common, so two cohorts differ in what is
measured and never in how honestly it is measured.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from functools import partial
from typing import Callable

from . import answer_block, docs_answer, docs_scorer, prompt, roundtrip_api, scorer, taxonomy

#: The default cohort. A pack that declares nothing gets exactly what it had before this module.
DEFAULT_COHORT = "api"


def _path_spellings(path: str, base_prefixes) -> list[str]:
    """The literal forms a documentation page might use for one ground-truth path.

    Only the base-prefix pairs, because that is the one rewriting a vendor is entitled to do and this
    project already models it (ADR-0013/0017): a spec may write the whole address while a guide
    writes the fragment after the base URL. No normalization beyond that, deliberately — see
    `conditions.audit_docs_truncation` for why an approximate matcher is safe there and a clever one
    would not be.

    A pack may declare more than one prefix (ADR-0039); each contributes its own pair. Accepts a bare
    string for the single-prefix packs that predate that widening.
    """
    if isinstance(base_prefixes, str):
        base_prefixes = [base_prefixes]
    out = [path]
    for base_prefix in base_prefixes or []:
        pre = "/" + base_prefix.strip("/")
        if path.startswith(pre):
            out.append(path[len(pre):] or "/")
        else:
            out.append(pre.rstrip("/") + path)
    return [s for s in dict.fromkeys(out) if s]


def _api_ground_truth_terms(task: dict, pack) -> list[tuple[str, list[str]]]:
    """`(item, acceptable spellings)` per ground-truth endpoint — the API cohort's search terms."""
    prefixes = getattr(pack, "declared_base_prefixes", None) or \
        getattr(pack, "endpoint_base_prefix", None)
    terms: list[tuple[str, list[str]]] = []
    for endpoint in (task.get("ground_truth") or {}).get("endpoints") or []:
        path = endpoint.get("path")
        if path:
            terms.append((path, _path_spellings(path, prefixes)))
    return terms


def _docs_ground_truth_terms(task: dict, pack) -> list[tuple[str, list[str]]]:
    return docs_scorer.ground_truth_terms(task)


def _api_context_preamble(label: str) -> str:
    """The API cohort's docs-context preamble, VERBATIM as it has always been.

    Public #67 records that this sentence is emitted whether or not anything was injected, which
    makes it a false statement in the prompt on a pack whose fetch retrieved nothing. It is left
    exactly as it is here on purpose: changing it changes what the model was asked, so every
    archived API run would stop being an answer to the prompt that produced it and five published
    numbers would stand as measurements of a prompt that no longer exists. That repair belongs to
    the deliberate re-baseline #67 describes, not to this cycle, and it is NOT applied backwards.
    """
    return (f"You have been given excerpts from {label} below. "
            "Use them to answer accurately.\n")


def _docs_context_preamble(label: str) -> str:
    """The docs cohort's preamble: none at all.

    This cohort is built without the excerpt-promise sentence FROM DAY ONE (ADR-0044). It has no
    archive to invalidate, so it starts on the far side of #67 rather than inheriting a defect and a
    queued repair. The injected context is the labelled page blocks alone, which promises nothing
    that may turn out not to be there.

    A direct consequence, stated rather than discovered: a docs `public-docs` number is not
    comparable to an API `public-docs` number, because the two conditions no longer ask the same
    question. That is one of three independent reasons the cohorts do not share a baseline — the
    others being a different dimension set and a per-pack context budget.
    """
    return ""


@dataclass(frozen=True)
class AnswerContract:
    """One cohort's question, parser, dimension set and scoring rule."""

    name: str
    dimensions: tuple[str, ...]
    dim_labels: dict[str, str]
    categories: tuple[str, ...]
    build_prompt: Callable[[str], str]
    parse: Callable[[str], object]
    render_block: Callable[..., str]
    score_task: Callable[..., scorer.TaskScore]
    answer_from_ground_truth: Callable[..., object]
    ground_truth_terms: Callable[[dict, object], list[tuple[str, list[str]]]]
    roundtrip_problems: Callable[[dict], list[str]]
    roundtrip_notes: Callable[[dict], list[str]]
    context_preamble: Callable[[str], str]
    #: Whether a truncated-away ground-truth value BLOCKS the pipeline or merely warns. See
    #: `factory.check_truncation` for the argument; it is a property of the cohort, not of a pack.
    truncation_blocks: bool = False
    #: Whether a declared dimension that NO task exercises blocks the pipeline or is reported as a
    #: warning (ADR-0045). Cohort-scoped for a measured reason, not a convenient one: when the gate
    #: was first run over every pack on disk, 13 of 18 already had such a dimension, so blocking the
    #: api cohort would have failed eleven published packs over a pre-existing condition this cycle
    #: is not repairing. The count is in ADR-0045 and each pack is filed. `docs` blocks from the
    #: start, because it has one measured pack and the next one is being authored now.
    coverage_blocks: bool = False
    #: Keys a PACK declared as unscored observations (ADR-0045), bound by `contract_for`. Empty on
    #: every base contract. These are recorded per run and are structurally incapable of scoring:
    #: they are not in `dimensions`, so no aggregate, table or overall can reach them.
    observations: tuple[str, ...] = ()
    notes: str = field(default="")


API_CONTRACT = AnswerContract(
    name="api",
    dimensions=scorer.DIMENSIONS,
    dim_labels={
        "endpoint": "endpoint",
        "method": "method",
        "api_version": "version",
        "auth_flow": "auth",
        "required_scopes": "scopes",
        "key_parameters": "params",
    },
    categories=taxonomy.CATEGORIES,
    build_prompt=prompt.build_prompt,
    parse=answer_block.parse,
    render_block=answer_block.render_block,
    score_task=scorer.score_task,
    answer_from_ground_truth=roundtrip_api.answer_from_ground_truth,
    ground_truth_terms=_api_ground_truth_terms,
    roundtrip_problems=roundtrip_api.roundtrip_problems,
    roundtrip_notes=roundtrip_api.roundtrip_notes,
    context_preamble=_api_context_preamble,
    truncation_blocks=False,
    notes="Six dimensions over an HTTP API surface (ADR-0002/0004).",
)

DOCS_CONTRACT = AnswerContract(
    name="docs",
    dimensions=docs_scorer.DIMENSIONS,
    dim_labels=docs_scorer.DIM_LABELS,
    categories=taxonomy.DOCS_CATEGORIES,
    build_prompt=docs_answer.build_prompt,
    parse=docs_answer.parse,
    render_block=docs_answer.render_block,
    score_task=docs_scorer.score_task,
    answer_from_ground_truth=docs_scorer.answer_from_ground_truth,
    ground_truth_terms=_docs_ground_truth_terms,
    roundtrip_problems=docs_scorer.roundtrip_problems,
    roundtrip_notes=docs_scorer.roundtrip_notes,
    context_preamble=_docs_context_preamble,
    # A docs answer IS the value the manual states, so a value the budget cropped away is not a
    # harder question — it is an unanswerable one. See `factory.check_truncation`.
    truncation_blocks=True,
    coverage_blocks=True,
    notes="Three dimensions over discrete engineering values published as manuals (ADR-0044).",
)

CONTRACTS: dict[str, AnswerContract] = {
    API_CONTRACT.name: API_CONTRACT,
    DOCS_CONTRACT.name: DOCS_CONTRACT,
}


def score_fields(score: scorer.TaskScore, contract: AnswerContract) -> dict:
    """The scored fields of a run record, for the runner and for `rebuild-report` alike.

    One function so the live path and the re-score path cannot drift about what a record contains —
    the drift `category.rollup_by_category` exists to prevent for group arithmetic, applied to the
    archive. `exhibit` is written only when a contract produced one, so every API record stays
    byte-identical and no committed `scores.json` moves.
    """
    fields = {
        "dimensions": {d: (score.dim(d).score if score.dim(d) else None)
                       for d in contract.dimensions},
        "endpoint_matches": score.endpoint_matches,
    }
    if score.exhibit:
        fields["exhibit"] = score.exhibit
    return fields


def score_response(task: dict, raw_text: str, contract: AnswerContract,
                   base_prefix: list[str] | None = None):
    """Parse + score one raw response under a contract. Returns `(TaskScore, parse_result)`.

    A format failure is a distinct outcome and is never scored zero — the rule ADR-0004 set for the
    API cohort, and the reason both contracts share `ParseResult`/`FormatFailure`.
    """
    parsed = contract.parse(raw_text)
    if parsed.is_failure:
        return scorer.format_failure_score(task["id"], parsed.failure.reason), parsed
    return contract.score_task(task, parsed.summary, base_prefix), parsed


def contract_for(pack) -> AnswerContract:
    """The answer contract for a loaded pack, by its declared cohort.

    Fails LOUDLY on an unknown cohort rather than falling back to the API contract. A pack that
    declares `cohort: dcos` would otherwise be scored on six dimensions its ground truth does not
    have, every one of them n/a, and would produce a green run measuring nothing — the vacuous-pass
    shape this project keeps closing.
    """
    name = getattr(pack, "cohort", DEFAULT_COHORT) or DEFAULT_COHORT
    if name not in CONTRACTS:
        known = ", ".join(sorted(CONTRACTS))
        raise KeyError(
            f"pack '{getattr(pack, 'vendor_id', '?')}' declares cohort '{name}', which has no "
            f"answer contract (known: {known}). A cohort is added in core with an ADR, never "
            f"assumed from a pack."
        )
    return bind_observations(CONTRACTS[name], getattr(pack, "unscored_observations", None))


def bind_observations(base: AnswerContract, observations: dict | None) -> AnswerContract:
    """Return `base` with a pack's declared unscored observations bound in (ADR-0045).

    Returns `base` ITSELF when a pack declares none — identity, not a copy — so every pack that
    predates this field keeps the exact contract object it had, and `contract is API_CONTRACT`
    stays true for the whole API cohort.

    A declared key that collides with a scored dimension or with a contract key raises, because the
    two failure modes a silent overwrite would produce are both invisible: a dimension quietly fed
    from an unscored channel, or an observation quietly scored. Raised as `KeyError` so the
    round-trip gate reports it as a written block rather than crashing the dispatcher.
    """
    keys = tuple(str(k) for k in (observations or {}))
    if not keys:
        return base
    if base.name != "docs":
        raise KeyError(
            f"cohort '{base.name}' has no unscored-observation channel, but the pack declares "
            f"{', '.join(keys)}. The channel exists for the docs contract only (ADR-0045); adding "
            "it to another cohort is an ADR, not a pack field."
        )
    clash = [k for k in keys if k in base.dimensions or k in docs_answer.KEYS]
    if clash:
        raise KeyError(
            f"unscored_observations names {', '.join(sorted(clash))}, which the contract already "
            "defines. An observation is recorded and never scored, so a name that collides with a "
            "scored dimension or a contract key would make one silently stand in for the other."
        )
    blank = [k for k in keys if not str((observations or {})[k]).strip()]
    if blank:
        raise KeyError(
            f"unscored_observations names {', '.join(sorted(blank))} with no written reason. The "
            "reason is what a reviewer disagrees with; a bare key is a value class arriving in the "
            "archive without anyone having decided it should."
        )
    return replace(
        base,
        observations=keys,
        build_prompt=partial(docs_answer.build_prompt, observations=dict(observations or {})),
        parse=partial(docs_answer.parse, observation_keys=keys),
    )
