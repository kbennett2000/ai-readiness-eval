"""The guards: the core ENGINE is vendor-agnostic, and the public repo names no prospect.

1. No core ENGINE module (`core/*.py`, excluding the test suite) may name a vendor — vendor specifics
   must arrive through a loaded Pack. The test suite MAY name SailPoint, which is the public reference
   pack (not a prospect) and is exercised for cross-pack coverage.
2. No tracked file in the public repo may name a measured prospect (they live in a private repo).
3. Nor may any git ref. Branch names are published as surely as file contents, and `git ls-files`
   cannot see them — a gap found only after a `cycle-NN-<vendor>` branch had already been pushed.
"""
import re
import subprocess
from pathlib import Path

import pytest

from core.pack import Pack

CORE_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = CORE_DIR.parent
ACME_PACK_DIR = CORE_DIR / "tests" / "fixtures" / "pack-acme"

# Tokens that would betray a hardcoded vendor in the engine. SailPoint is the public reference pack, so
# its name/spec-prefix are what the engine must NOT bake in (they belong in packs/sailpoint/, not core).
VENDOR_TOKENS = re.compile(r"sailpoint|isc_spec_context|developer\.sailpoint|idn/", re.IGNORECASE)

# Prospect names that must never appear anywhere tracked in the PUBLIC repo (privacy, cycle 2).
# Every prospect the factory has carded belongs here — the list went stale between cycles 2 and 6,
# which let a recon note naming two later prospects reach a commit before the guard objected. Since
# cycle 9 the name is added at the START of a vendor's cycle, before any recon note exists to leak:
# a guard that trails the work protects the cycle after the one that needed it.
#
# `thycotic` is listed beside `delinea` because a vendor's FORMER brand identifies it just as well,
# and this one still hosts that vendor's published spec — so a stray spec URL in a public file would
# name the prospect without ever spelling its current name.
#
# A target the queue has PARKED is listed too. `blocked` records what this instrument will measure; it
# says nothing about whose name is ours to publish, and a parked target can be un-parked later.
PROSPECT_TOKENS = re.compile(
    r"saviynt|okta|cyberark|oneidentity|pingone|delinea|thycotic|beyondtrust"
    r"|runpod|hedera|hashgraph|orcarouter|openzeppelin",
    re.IGNORECASE,
)

# Two prospects' names are also ordinary words in this domain, so they are matched only as capitalized
# proper nouns. The reference pack legitimately says "exactly one identity" and "one identity's
# accounts"; and a scheduling note may legitimately say a run happens at midnight. Case-insensitive
# matching would fire on that ordinary prose, and a guard that cries wolf gets routed around.
PROSPECT_TOKENS_CASED = re.compile(r"One Identity|Midnight")


def _engine_py_files():
    """Top-level engine modules — core/*.py, NOT core/tests/ (tests may name the reference pack)."""
    return sorted(CORE_DIR.glob("*.py"))


def test_no_vendor_token_in_core_engine():
    offenders = []
    for path in _engine_py_files():
        for i, line in enumerate(path.read_text().splitlines(), 1):
            if VENDOR_TOKENS.search(line):
                offenders.append(f"{path.relative_to(REPO_ROOT)}:{i}: {line.strip()}")
    assert not offenders, (
        "the core engine must carry no vendor token; found:\n" + "\n".join(offenders)
    )


def test_public_repo_names_no_prospect():
    """Every tracked file (except this guard, which spells the tokens as patterns) is prospect-free."""
    try:
        tracked = subprocess.check_output(
            ["git", "ls-files"], cwd=REPO_ROOT, text=True
        ).splitlines()
    except (subprocess.CalledProcessError, FileNotFoundError):
        pytest.skip("not a git checkout")
    this_file = Path(__file__).resolve()
    offenders = []
    for rel in tracked:
        p = REPO_ROOT / rel
        if p.resolve() == this_file or not p.is_file():
            continue
        try:
            text = p.read_text(errors="ignore")
        except OSError:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            if PROSPECT_TOKENS.search(line) or PROSPECT_TOKENS_CASED.search(line):
                offenders.append(f"{rel}:{i}: {line.strip()[:80]}")
    assert not offenders, (
        "the public repo must name no measured prospect (they live in the private packs repo); found:\n"
        + "\n".join(offenders)
    )


def test_public_repo_ref_names_no_prospect():
    """Branch names are published too, and `git ls-files` structurally cannot see them.

    Found the ordinary way: a cycle branched as `cycle-NN-<vendor>` and pushed, putting a measured
    prospect's name on a world-visible ref while `test_public_repo_names_no_prospect` stayed green —
    it reads tracked file CONTENT, and a ref is neither a file nor tracked. The disclosure is the
    same one that guard exists to prevent, reached by a route it does not cover.

    Deleting a ref is destructive, so this test does not repair anything. It fails until the operator
    deletes the branch upstream and prunes, which is the point: an unattended cycle records the
    problem and cannot forget it, rather than recording it once in a report nobody re-reads.
    """
    try:
        refs = subprocess.check_output(
            ["git", "for-each-ref", "--format=%(refname)", "refs/heads", "refs/remotes"],
            cwd=REPO_ROOT, text=True,
        ).splitlines()
    except (subprocess.CalledProcessError, FileNotFoundError):
        pytest.skip("not a git checkout")
    offenders = [r for r in refs if PROSPECT_TOKENS.search(r) or PROSPECT_TOKENS_CASED.search(r)]
    assert not offenders, (
        "a git ref names a measured prospect, and refs are world-visible:\n"
        + "\n".join(offenders)
        + "\n\nDelete it upstream, then prune the local tracking ref:\n"
        "  git push origin --delete <branch> && git fetch --prune\n"
        "A stale remote-tracking ref fails this test after the upstream branch is gone; prune first."
    )


def test_no_vendor_token_in_pack_acme_fixture():
    # The test fixture itself must stay vendor-neutral, else the guard above would have to whitelist it.
    for path in sorted(ACME_PACK_DIR.rglob("*")):
        if path.is_file():
            assert not VENDOR_TOKENS.search(path.read_text()), f"vendor token leaked into {path}"


def test_conditions_use_pack_prefix_not_a_constant(acme_pack):
    """The mcp tool prefix is read from the pack, not baked into core — swap the pack, swap the prefix."""
    from core.conditions import McpCondition
    pol = McpCondition(acme_pack).cli_policy()
    assert pol.allowed_tools == ["mcp__acme__*", "ToolSearch"]
    # a differently-configured pack yields a different prefix, proving it is not a constant
    import copy
    other = copy.copy(acme_pack)
    other.context_layer = copy.copy(acme_pack.context_layer)
    other.context_layer.mcp_tool_prefix = "mcp__widgets__"
    assert McpCondition(other).cli_policy().allowed_tools == ["mcp__widgets__*", "ToolSearch"]


def test_preflight_marker_comes_from_pack(acme_pack):
    """The canary project marker is pack-supplied, not a module constant in core."""
    import core.preflight as preflight
    src = Path(preflight.__file__).read_text()
    assert "PROJECT_MARKER =" not in src, "core.preflight must not hardcode a project marker"
    assert acme_pack.project_marker == "acme-eval-project"


@pytest.mark.parametrize("token", ["sailpoint", "SailPoint", "isc_spec_context", "idn/"])
def test_guard_regex_actually_matches_known_vendor_tokens(token):
    # Guard the guard: ensure the detector would fire on the tokens it claims to catch.
    assert VENDOR_TOKENS.search(f"prefix {token} suffix")


@pytest.mark.parametrize("token", PROSPECT_TOKENS.pattern.split("|"))
def test_prospect_regex_actually_matches_every_token_it_claims(token):
    """Guard the guard, prospect side — the equivalent of the vendor-token check above.

    Its absence was noticed the ordinary way: removing one token from the pattern on purpose left the
    ref scan failing anyway, because a DIFFERENT token still matched the same ref. A break test that
    cannot fail for the reason you intended proves nothing, so each token is now asserted on its own.

    The token list is READ OFF THE PATTERN rather than restated beside it. Restating it meant a token
    added to the pattern was covered by nothing until someone remembered to add it here too, and the
    first tokens to be forgotten are always the newest — the ones no cycle has exercised yet.

    What deriving it CANNOT do, said plainly: it proves every token the pattern claims actually fires,
    never that every prospect is claimed. A target added to the private queue and forgotten here is
    invisible to this test and to every other test in this repository, because the list of prospects
    lives in a repository this one cannot read. That gap is procedural (add the token when the target
    enters the queue) and is registered as an ungated hazard.
    """
    assert PROSPECT_TOKENS.search(f"cycle-09-{token}"), f"{token!r} is listed but never fires"
    assert PROSPECT_TOKENS.search(f"prefix {token.upper()} suffix"), f"{token!r} is case-sensitive"


@pytest.mark.parametrize("token", PROSPECT_TOKENS_CASED.pattern.split("|"))
def test_cased_prospect_regex_fires_on_the_proper_noun_only(token):
    """Derived the same way, and asserting BOTH halves of the bargain these tokens were given.

    A cased token buys leniency on ordinary prose, so it has to pay for it: it must still fire on the
    proper noun, and it must still stay silent on the lowercase word.
    """
    assert PROSPECT_TOKENS_CASED.search(f"cycle-06-{token}"), f"{token!r} is listed but never fires"
    assert not PROSPECT_TOKENS_CASED.search(f"prefix {token.lower()} suffix"), \
        f"{token!r} is cased-only precisely so the lowercase word does not fire"


def test_the_cased_tokens_stay_silent_on_the_prose_they_were_carved_out_for():
    # The concrete sentences that forced the carve-out, kept as literals so the reason survives.
    assert not PROSPECT_TOKENS_CASED.search("exactly one identity's accounts")
    assert not PROSPECT_TOKENS_CASED.search("the nightly grid runs at midnight")
