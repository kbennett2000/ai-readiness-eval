"""Deterministic scorer for the DOCS cohort (ADR-0044).

Three dimensions, each a mechanical comparison a reviewer can reproduce from the archived raw
response — the same bar `core/scorer.py` holds for the API cohort, applied to a surface that has no
endpoint, method, version, auth flow, scope or parameter anywhere in it.

    catalog_number     which part meets the stated requirement
    firmware_version   the device firmware revision required
    software_version   the programming-software version required

WHY THE PAIRING IS NOT A FOURTH DIMENSION. Firmware and software compatibility is a *pairing* of two
independently-published values, and knowing them separately is worth much less than pairing them
correctly. It is still not scored as its own dimension: with `overall_accuracy` defined as the mean
of applicable dimensions, adding it would let compatibility drive three quarters of the headline
while the catalog class drives one. It is computed and reported instead — `exhibit["pairing_ok"]`
per run — which is the same treatment ADR-0037 gives a reporting axis that must not move a number.

WHAT IS RECORDED AND NOT SCORED. `publication` — the publication number the answer cites — is kept
per run in the exhibit. It costs nothing, and it is the mechanical signal a pack needs to ask
whether a model answered a question about one product line with a document about a neighbouring one.
Core only records it; which publication numbers count as a near neighbour is a vendor fact and stays
in the pack.
"""
from __future__ import annotations

import re

from .docs_answer import DocsAnswer
from .scorer import DimensionScore, TaskScore

#: The three ADR-0044 dimensions. Deliberately disjoint from `scorer.DIMENSIONS`, and a test asserts
#: it: a name shared between two contracts would let a docs cell be read into an API column.
DIMENSIONS = ("catalog_number", "firmware_version", "software_version")

DIM_LABELS = {
    "catalog_number": "catalog",
    "firmware_version": "firmware",
    "software_version": "software",
}

# A dotted (or bare) numeric version anywhere in a string: `35`, `35.011`, `31.00.01`, `v38`.
_VERSION_RE = re.compile(r"(?<![\w.])v?(\d+(?:\.\d+)*)(?![\w.])", re.IGNORECASE)

_WHITESPACE_RE = re.compile(r"\s+")


# --------------------------------------------------------------------------- #
# Normalization. Each rule states the direction it must not go.
# --------------------------------------------------------------------------- #

def normalize_catalog(value: str | None) -> str:
    """Canonical form of a catalog / part number: upper-cased, whitespace collapsed.

    WHAT THIS DELIBERATELY DOES NOT DO IS FOLD A VARIANT SUFFIX. A conformal-coated, extended-
    temperature or no-stored-energy variant is a different orderable part with a different price and
    a different environmental rating, and a buyer handed the wrong one has been given a wrong answer.
    So `ABC-1234X` and `ABC-1234X-K` never compare equal, and a must-not-fold test pins it — this is
    the one normalization here that could manufacture a score, because the dimension is
    containment-scored and a fold can only ever add a match.

    Hyphens, slashes and series letters are likewise left alone. The only differences collapsed are
    ones that carry no information at all: case, and surrounding or repeated whitespace.
    """
    if not value:
        return ""
    return _WHITESPACE_RE.sub(" ", str(value).strip()).upper()


def version_tuples(text: str | None) -> list[tuple[int, ...]]:
    """Every version a string names, as comparable integer tuples, in order of appearance.

    A leading `v` is folded and each dot-separated segment is read as an integer, so a leading zero
    carries no meaning: `35.011` and `35.11` both read as `(35, 11)`. That fold is the forgiving
    direction on notation, in the same family as ADR-0020 and ADR-0025, and it rests on a fact about
    the surface being measured: revisions are published in one zero-padded notation, so the two
    spellings are two ways of writing one revision rather than two revisions. It is pinned by test
    and named in ADR-0044 as an assumption, because a vendor that shipped both `35.11` and `35.011`
    as DIFFERENT revisions would make this fold wrong.

    Returns a LIST because a model may name several versions in one field, and the caller decides
    what to do about that rather than this function silently picking one.
    """
    if not text:
        return []
    out: list[tuple[int, ...]] = []
    for match in _VERSION_RE.finditer(str(text)):
        out.append(tuple(int(seg) for seg in match.group(1).split(".")))
    return out


def version_satisfies(required: str | None, answer: str | None) -> bool:
    """Does the answer name a version that satisfies this requirement?

    The rule is **precision-asymmetric**, and the asymmetry is the whole design — the same shape as
    ADR-0024's parameter-ancestry rule, and refused in the same direction:

      - An answer MORE precise than a major-only requirement satisfies it: `38.01` satisfies `38`.
        A requirement written at major precision is a statement about the major revision, and any
        revision within it meets it.
      - An answer LESS precise than a stated precise requirement does NOT satisfy it: `31` does not
        satisfy `31.00.01`. When a vendor states three components, the later ones are the whole
        point of stating them — an integrator who installs `31.00.00` has not met the requirement —
        and crediting the vague answer is the direction that manufactures a score. Pinned by a
        must-not test.

    A field naming several versions is scored as ANY-OF: it passes if any named version satisfies
    the requirement. That is the judgment call `required_scopes` already makes for the API cohort
    and is cited to it. Because it is the direction that can only ever credit, hedging is counted
    rather than trusted — see `hedge_count`, which the exhibit records for every run.
    """
    req = version_tuples(required)
    if not req:
        return False
    want = req[0]
    return any(got[:len(want)] == want for got in version_tuples(answer) if len(got) >= len(want))


def hedge_count(answer: str | None) -> int:
    """How many DISTINCT versions one answer field names. 1 is a straight answer; more is a hedge.

    Recorded rather than punished. `version_satisfies` is any-of, so an answer listing many versions
    is more likely to contain the right one — and a scorer that cannot see that is a scorer that
    cannot report it. The count goes in the exhibit and onto the card; it changes no score.
    """
    return len(set(version_tuples(answer)))


# --------------------------------------------------------------------------- #
# Scoring.
# --------------------------------------------------------------------------- #

def score_task(task: dict, answer: DocsAnswer, base_prefix=None) -> TaskScore:
    """Score one parsed docs answer against one task's ground truth.

    `base_prefix` is accepted and ignored: it is the API cohort's endpoint-address tolerance
    (ADR-0017) and has no meaning on a surface with no addresses. The parameter exists so both
    contracts present one calling signature to the runner, the round-trip control and
    `rebuild-report`.

    A value class the task does not ask about is `None` — not applicable — exactly as the API
    scorer reports a task with no required scopes. It is never scored zero, and it is excluded from
    the means, so a catalog-selection task is not penalised for saying nothing about firmware.
    """
    gt = task["ground_truth"]
    result = TaskScore(task_id=task["id"])

    # --- catalog_number (any-of overlap; the `required_scopes` judgment call) ---
    gt_catalog = {normalize_catalog(c) for c in (gt.get("catalog_numbers") or [])}
    gt_catalog.discard("")
    ans_catalog = {normalize_catalog(c) for c in (answer.catalog_numbers or [])}
    ans_catalog.discard("")
    if not gt_catalog:
        result.dimensions["catalog_number"] = DimensionScore(
            "catalog_number", None, "no catalog number in ground truth (n/a)",
        )
    else:
        overlap = gt_catalog & ans_catalog
        result.dimensions["catalog_number"] = DimensionScore(
            "catalog_number", 1.0 if overlap else 0.0,
            f"matched {sorted(overlap) or '[]'} of acceptable {sorted(gt_catalog)}",
        )

    # --- firmware_version / software_version (precision-asymmetric) -----------
    for dim, gt_key, ans_value in (
        ("firmware_version", "firmware_version", answer.firmware_version),
        ("software_version", "software_version", answer.software_version),
    ):
        required = gt.get(gt_key)
        if not required:
            result.dimensions[dim] = DimensionScore(
                dim, None, f"no {dim.replace('_', ' ')} in ground truth (n/a)",
            )
            continue
        ok = version_satisfies(required, ans_value)
        result.dimensions[dim] = DimensionScore(
            dim, 1.0 if ok else 0.0,
            f"required {required}, got {ans_value or '(none)'}",
        )

    # --- recorded, never scored ----------------------------------------------
    fw, sw = result.dimensions["firmware_version"], result.dimensions["software_version"]
    pairing_applicable = fw.score is not None and sw.score is not None
    result.exhibit = {
        "publication": answer.publication,
        "catalog_numbers": list(answer.catalog_numbers or []),
        # The derived compatibility figure. `None` when the task does not ask for both halves, so a
        # card can never average a pairing over tasks that had no pairing to get right.
        "pairing_ok": bool(fw.score == 1.0 and sw.score == 1.0) if pairing_applicable else None,
        "firmware_hedge": hedge_count(answer.firmware_version),
        "software_hedge": hedge_count(answer.software_version),
    }
    # A pack's declared unscored observations (ADR-0045), recorded beside the other exhibits and
    # never read by any branch above. They arrive namespaced so that reading the exhibit tells a
    # reviewer which figures the contract computed and which a pack asked for.
    if answer.observations:
        result.exhibit["observed"] = {k: v for k, v in answer.observations.items()}
        # What the task's own key says the answer should have been, so the pair can be compared
        # after the fact without re-reading every task file. Absent when the task declares none.
        expected = {k: (str(gt["observations"][k]) if (gt.get("observations") or {}).get(k) else None)
                    for k in answer.observations}
        if any(v is not None for v in expected.values()):
            result.exhibit["observed_expected"] = expected
    return result


def answer_from_ground_truth(task: dict, *, canonical_auth: bool = False) -> DocsAnswer:
    """The answer a model would give if it reproduced this task's ground truth exactly (ADR-0010).

    `canonical_auth` is accepted and ignored — it is the API cohort's mock-only convenience for a
    dimension this cohort does not have. Both contracts present one signature to the round-trip
    control and the `--mock` provider.
    """
    gt = task.get("ground_truth") or {}
    publication = gt.get("publication") or {}
    return DocsAnswer(
        catalog_numbers=[str(c) for c in (gt.get("catalog_numbers") or [])],
        firmware_version=(str(gt["firmware_version"]) if gt.get("firmware_version") else None),
        software_version=(str(gt["software_version"]) if gt.get("software_version") else None),
        publication=(str(publication.get("number")) if publication.get("number") else None),
        # The round-trip control renders this answer back into a block and re-parses it, so the
        # declared observations have to survive the trip. They are never scored, so they can never
        # make the control pass — only a missing key could make it fail, which is the safe direction.
        observations={k: (str(v) if v is not None else None)
                      for k, v in (gt.get("observations") or {}).items()},
    )


def ground_truth_terms(task: dict) -> list[tuple[str, list[str]]]:
    """`(item, acceptable spellings)` for every ground-truth VALUE this task will be scored on.

    Consumed by the contract-aware truncation audit, which asks whether the documentation we inject
    still contains the answer we are about to score against. For the API cohort that question is
    about endpoint paths; here it is about the values themselves, and the spellings are the literal
    strings a manual might carry.
    """
    gt = task.get("ground_truth") or {}
    terms: list[tuple[str, list[str]]] = []
    for catalog in gt.get("catalog_numbers") or []:
        text = str(catalog).strip()
        if text:
            terms.append((f"catalog:{text}", [text]))
    for key in ("firmware_version", "software_version"):
        value = gt.get(key)
        if value:
            terms.append((f"{key}:{value}", [str(value).strip()]))
    return terms


def roundtrip_problems(task: dict) -> list[str]:
    """Blocking round-trip checks specific to this contract (ADR-0010's fourth guarantee).

    The API cohort blocks a task whose `auth_flow` names no login style the scorer can positively
    test. The docs analogue is a task that declares no scorable value at all: every dimension would
    report n/a, the task would pass the control by measuring nothing, and a grid would burn on it.
    """
    gt = task.get("ground_truth") or {}
    has_catalog = bool(gt.get("catalog_numbers"))
    has_version = bool(gt.get("firmware_version") or gt.get("software_version"))
    if not (has_catalog or has_version):
        return [
            "ground truth declares no catalog number and no version, so every dimension is n/a — "
            "the task would pass the control vacuously and measure nothing"
        ]
    return []


def roundtrip_notes(task: dict) -> list[str]:
    """Non-blocking notes: shapes that score but measure less than they appear to.

    A task declaring only one half of the compatibility pairing still scores, and should — plenty of
    real questions are about firmware alone. It is worth SAYING, though, because the pairing figure
    the card reports is n/a for that task, and a reader comparing pairing counts across tasks needs
    to know the denominator is not the task count.
    """
    gt = task.get("ground_truth") or {}
    has_fw, has_sw = bool(gt.get("firmware_version")), bool(gt.get("software_version"))
    if has_fw != has_sw:
        only = "firmware_version" if has_fw else "software_version"
        return [
            f"ground truth declares {only} but not its partner, so the compatibility pairing is "
            "n/a for this task and it contributes nothing to the pairing figure"
        ]
    return []
