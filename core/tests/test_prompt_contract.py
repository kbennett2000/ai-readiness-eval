"""The answer-block contract is a pinned instrument, not editable copy.

Every condition, every pack and every measured model reads the same suffix from
`core/prompt.py`. A word changed there changes what the model is nudged to say,
so scores taken before and after are not comparable — and unlike a scorer rule,
the change cannot be re-applied to archived transcripts by `rebuild-report`.

These tests pin the part of the contract that is known to bias a scored
dimension: the single `auth_flow` example. It names one of the five login styles
in `scorer._AUTH_STYLES` (ADR-0011 rule 5), which plainly tilts answers toward
OAuth wording on products that do not use it. That bias is *disclosed* on the
cards rather than fixed here, because fixing it makes every previously measured
vendor incomparable. Changing it is reserved for a deliberate cohort re-baseline,
bundled with any model change — at which point the whole cohort re-runs together
and these pins are updated in that same cycle.
"""
from core import scorer
from core.prompt import ANSWER_BLOCK_SUFFIX


def test_the_auth_flow_example_is_pinned():
    # Both places the contract shows the field: the inline hint and the worked example.
    assert 'auth_flow:            # short phrase naming the auth mechanism, e.g. "OAuth2 bearer token"' \
        in ANSWER_BLOCK_SUFFIX
    assert "auth_flow: OAuth2 bearer token" in ANSWER_BLOCK_SUFFIX


def test_the_contract_offers_exactly_one_login_style():
    """The size of the bias, measured with the scorer's own vocabulary.

    Asserting the *set* rather than the strings is the load-bearing half: it fails
    if a future edit adds a second example style (which would change the bias
    rather than remove it) as well as if the one example is swapped.
    """
    assert scorer._auth_concepts(ANSWER_BLOCK_SUFFIX) == {"bearer-token"}
