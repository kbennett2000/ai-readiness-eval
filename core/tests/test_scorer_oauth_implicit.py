"""ADR-0040 — `oauth2-implicit` is the seventh login style the scorer can positively test.

ADR-0011 established the rule this file defends: a dimension does not score unless it can be
POSITIVELY tested. A style the scorer cannot name canonicalizes to `unknown` on BOTH sides, so a
ground truth naming it scores 1.0 against any answer that also names none — the dimension reads as
applicable while measuring nothing. That is why an unlisted style blocks `roundtrip` rather than
drawing a note, and it is exactly what a vendor whose published specification declares
`flow: implicit` triggered.

The vendor is a measured prospect and cannot be named here, so the fixtures are neutral.

Every assertion below was verified by breaking it on purpose.
"""
from core import scorer


def canon(text):
    return scorer.canonical_auth_flow(text)


# --------------------------------------------------------------------------------------------- #
# The style exists and is positively testable.
# --------------------------------------------------------------------------------------------- #

def test_the_style_is_declarable_by_a_pack():
    assert "oauth2-implicit" in scorer.KNOWN_AUTH_STYLES


def test_both_markers_canonicalize():
    assert canon("OAuth 2.0 implicit grant against the tenant authorization host") == "oauth2-implicit"
    assert canon("the API uses the OAuth2 implicit flow") == "oauth2-implicit"


def test_a_spec_style_declaration_canonicalizes():
    """The shape a Swagger 2.0 `securityDefinitions` block produces in ground-truth prose."""
    gt = ("OAuth 2.0. The document declares `type: oauth2`, `flow: implicit`, "
          "`authorizationUrl: https://<host>` — with no token URL and no scope list. "
          "The implicit grant is what the artifact states.")
    assert canon(gt) == "oauth2-implicit"


# --------------------------------------------------------------------------------------------- #
# PRECEDENCE. Each of these was inverted on purpose to confirm the ordering is load-bearing.
# --------------------------------------------------------------------------------------------- #

def test_it_outranks_bearer_and_access_token():
    """The inversion this entry exists to prevent.

    The implicit grant returns the access token straight from the authorization endpoint, so its
    prose necessarily names that token. Below `bearer-token`, this exact ground truth would
    canonicalize to `bearer-token` while the precise answer "OAuth2 implicit flow" canonicalized to
    `unknown` — scoring the exact answer 0 and the vaguer one 1.
    """
    gt = "OAuth2 implicit grant; the returned access token is sent as `Authorization: Bearer <token>`"
    assert canon(gt) == "oauth2-implicit"
    assert canon("send the access token as a bearer token") == "bearer-token"


def test_client_credentials_still_wins_when_stated():
    """A published pack stating client credentials keeps it, even contrasting with implicit."""
    assert canon("OAuth2 client credentials, not the implicit grant") == "oauth2-client-credentials"


def test_authorization_code_still_wins_when_stated():
    assert canon("OAuth2 authorization code with PKCE, replacing the implicit flow") == \
        "oauth2-authorization-code"


# --------------------------------------------------------------------------------------------- #
# THE MUST-NOT-FIRE PROPERTIES. A marker that is too wide re-canonicalizes published ground truth,
# which moves archived cells. `implicit` alone is the trap, and it is pinned here.
# --------------------------------------------------------------------------------------------- #

def test_bare_implicit_is_not_a_marker():
    """Ordinary prose says "implicitly" and "implicit" without describing a grant type."""
    assert canon("the tenant is implicit in the host name; send your API key") == "api-key"
    assert canon("scopes are granted implicitly by the security group") == "unknown"


def test_the_word_inside_another_style_does_not_hijack_it():
    assert canon("HMAC request signature; the key is implicit in the client id") == "hmac-signature"
    assert canon("Basic authentication — credentials are implicit in the URL") == "basic-auth"


def test_an_unrelated_flow_word_does_not_fire():
    assert canon("a flow that implicitly refreshes the session") == "session-token"


def test_nothing_that_names_no_style_gains_one():
    assert canon("send credentials as documented") == "unknown"
