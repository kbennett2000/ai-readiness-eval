"""The guards: the core ENGINE is vendor-agnostic, and the public repo names no prospect.

1. No core ENGINE module (`core/*.py`, excluding the test suite) may name a vendor — vendor specifics
   must arrive through a loaded Pack. The test suite MAY name SailPoint, which is the public reference
   pack (not a prospect) and is exercised for cross-pack coverage.
2. No tracked file the project AUTHORED may name a measured prospect (they live in a private repo).
   "Authored" is doing real work there: imported evidence archives quote whatever the measured model
   said, and a model names third-party products in its example payloads. Those archives are frozen —
   a published number rests on them — so they are excluded by name, and the exclusion's extent is
   itself asserted below.
3. Nor may any git ref. Branch names are published as surely as file contents, and `git ls-files`
   cannot see them — a gap found only after a `cycle-NN-<vendor>` branch had already been pushed.
4. A prospect is named by what it SELLS as well as by what it is called. Naming a handful of a
   vendor's distinctive products identifies it exactly as well as naming the vendor, and no token
   derived from an id can ever match one, so product names are declared explicitly (ADR-0028).

**What this guard structurally cannot do, and the rule that covers it.** It matches a list, so it can
only ever match a name it has been told. A target with no queue entry yet contributes ZERO tokens —
the guard is not weak about it, it is silent — and cycles naturally write prose (an ADR, a plan)
before the queue entry exists. No list-based guard can close that; only ordering can. **The standing
rule is therefore: add the queue entry, with its name and product tokens, BEFORE writing any public
prose about a target.** That rule is recorded here, in a tracked file that appears in a PR diff,
because it previously lived only in a gitignored handoff note — invisible to review, which is where
this class of mistake is actually caught.

**This file used to be the leak.** A plaintext matcher must spell the literals it matches, so the
guard listed every prospect and then exempted itself from its own rule — making the one tracked file
excused from "no tracked file may name a prospect" a better-organized roster than any leak the rule
prevents, in a repository whose visibility is PUBLIC. The list now loads at runtime from the private
packs repo (ADR-0018), this file names nobody, and the exemption is gone: the scan below reads its own
source like every other tracked file.
"""
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from core.factory import load_queue
from core.pack import Pack

CORE_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = CORE_DIR.parent
ACME_PACK_DIR = CORE_DIR / "tests" / "fixtures" / "pack-acme"

# Tokens that would betray a hardcoded vendor in the engine. SailPoint is the public reference pack, so
# its name/spec-prefix are what the engine must NOT bake in (they belong in packs/sailpoint/, not core).
# These stay literal: SailPoint is published on purpose and is not a prospect.
VENDOR_TOKENS = re.compile(r"sailpoint|isc_spec_context|developer\.sailpoint|idn/", re.IGNORECASE)

PACKS_DIR_ENV = "AIRE_PACKS_DIR"        # already the engine's packs-root variable (core/__main__.py)
QUEUE_ENV = "AIRE_QUEUE"                # already the engine's queue-path variable
GUARD_REQUIRED_ENV = "AIRE_GUARD_REQUIRED"   # set => a skip here is a FAILURE (ADR-0042)

# Values that mean "not required". Anything else — including the empty-ish typo `AIRE_GUARD_REQUIRED=`
# — is handled below; see `_guard_is_required` for why the unset case and the false case are the same
# answer while a typo'd path is not.
_FALSEY = {"", "0", "false", "no", "off"}


@dataclass
class _Prospects:
    """The name list, loaded from outside this repository — or the reason there isn't one."""
    tokens: list[str] = field(default_factory=list)          # matched case-insensitively
    cased_tokens: list[str] = field(default_factory=list)    # matched exactly as written
    pattern: re.Pattern | None = None
    cased_pattern: re.Pattern | None = None
    # Cased NAME tokens that opted into WHOLE-WORD matching (ADR-0049). The unbounded default above
    # rests on ADR-0028's argument that over-matching a vendor name is free because a vendor name is
    # distinctive. That is true of a coined name and false of a short acronym, which sits inside
    # ordinary words — and an acronym is a perfectly ordinary way for a company to be known. Opt-in
    # per token, so no existing declaration changes behaviour: a name is only bounded when its entry
    # says so. The cost is real and is paid at the declaration site, not hidden here — bounded
    # matching cannot see a name inside a compound like a hostname, so an entry that opts in is
    # expected to declare a companion token covering that. See `leak_guard_bounded_name_tokens`.
    name_cased_bounded_tokens: list[str] = field(default_factory=list)
    name_cased_bounded_pattern: re.Pattern | None = None
    # Product names are matched WHOLE-WORD; vendor names are matched as substrings. The asymmetry is
    # deliberate and was forced by evidence (ADR-0028). A vendor name is distinctive, so over-matching
    # it is free and catches `<name>-api` and `<name>'s`. A product name is frequently ordinary
    # technical English, and unbounded it is not merely noisy but unusable: on the first run of this
    # widened guard, one product token matched a longer English word in six ADR headers and another
    # matched a substring of an unrelated camelCase identifier in a fixture — eight false positives
    # against one true one. A guard that cries wolf at that ratio is a guard someone switches off.
    # (The offending tokens are not quoted here. Spelling them would reintroduce the leak into the
    # very comment explaining the fix — which is exactly what the first draft of it did.)
    product_tokens: list[str] = field(default_factory=list)
    product_cased_tokens: list[str] = field(default_factory=list)
    product_pattern: re.Pattern | None = None
    product_cased_pattern: re.Pattern | None = None
    skip: str = ""      # set => the private repo is not configured; skipping is correct
    error: str = ""     # set => it IS configured and is broken; that must be loud, never a skip

    def search(self, text: str) -> bool:
        return bool((self.pattern and self.pattern.search(text))
                    or (self.cased_pattern and self.cased_pattern.search(text))
                    or (self.name_cased_bounded_pattern
                        and self.name_cased_bounded_pattern.search(text))
                    or (self.product_pattern and self.product_pattern.search(text))
                    or (self.product_cased_pattern and self.product_cased_pattern.search(text)))


def _load_prospects() -> _Prospects:
    """Build the name list from the private packs repo: queue entries plus pack directory names.

    Both sources are needed and neither subsumes the other. Vendors carded before the queue existed
    have a pack directory and no entry; every unstarted target has an entry and no directory.

    A pack directory whose name matches a queue id contributes nothing extra — the entry has already
    declared that target's tokens, and the entry is allowed to NARROW them (see
    `QueueEntry.leak_guard_tokens`). Letting the directory name back in would silently undo a
    deliberate narrowing, which is how an id that is also an ordinary word starts firing on prose.
    """
    packs_dir = os.environ.get(PACKS_DIR_ENV)
    if not packs_dir:
        return _Prospects(skip=(
            f"{PACKS_DIR_ENV} is unset, so the prospect name list cannot be loaded. That list lives in "
            f"the private packs repo and deliberately not in this one (ADR-0018). Point "
            f"{PACKS_DIR_ENV} at that checkout to run this guard. An outside clone of this public "
            f"repository cannot run it, which is expected and is why this is a skip."
        ))

    def broken(detail: str) -> _Prospects:
        return _Prospects(error=(
            f"{PACKS_DIR_ENV}={packs_dir!r} is set, so the prospect guard must run — but {detail}. "
            f"A configured-and-broken name source is a failure, never a skip: skipping here would "
            f"mean a typo in one environment variable silently disables the leak guard."
        ))

    root = Path(packs_dir).expanduser()
    if not root.is_dir():
        return broken("it is not a directory")
    queue_path = (Path(os.environ[QUEUE_ENV]).expanduser() if os.environ.get(QUEUE_ENV)
                  else root / "queue.yaml")
    if not queue_path.is_file():
        return broken(f"no queue file at {queue_path}")
    try:
        entries = load_queue(queue_path)
    except Exception as exc:                                  # noqa: BLE001 - any parse failure is fatal
        return broken(f"{queue_path} did not load: {exc}")

    tokens: list[str] = []
    cased: list[str] = []
    cased_bounded: list[str] = []
    products: list[str] = []
    products_cased: list[str] = []
    for entry in entries:
        ins, cas = entry.leak_guard_tokens()
        tokens += ins
        cased += cas
        # Raises if an entry declares the same token bounded AND unbounded, which would read as an
        # opt-in and behave as none. `load_queue` already surfaces it, so reaching it here means a
        # caller built entries some other way.
        cased_bounded += entry.leak_guard_bounded_name_tokens()
        p_ins, p_cas = entry.leak_guard_product_tokens()
        products += p_ins
        products_cased += p_cas
    queue_ids = {e.id for e in entries}
    for pack_yaml in sorted(root.glob("*/pack.yaml")):
        name = pack_yaml.parent.name
        if name in queue_ids:
            continue
        collapsed = re.sub(r"[-_\s]+", "", name)
        tokens += [name] + ([collapsed] if collapsed != name else [])

    tokens = list(dict.fromkeys(t for t in tokens if t.strip()))
    cased = list(dict.fromkeys(c for c in cased if c.strip()))
    cased_bounded = list(dict.fromkeys(c for c in cased_bounded if c.strip()))
    products = list(dict.fromkeys(t for t in products if t.strip()))
    products_cased = list(dict.fromkeys(c for c in products_cased if c.strip()))
    if not tokens and not cased:
        return broken("it yielded no names at all, so the guard would match nothing and pass green")

    def bounded(items: list[str], flags: int = 0) -> re.Pattern | None:
        """Whole-word alternation. `\\b` is correct at both ends for every token shape used here —
        products are named in word characters, including multi-word names like `Data Fabric`."""
        if not items:
            return None
        return re.compile(r"\b(?:" + "|".join(re.escape(t) for t in items) + r")\b", flags)

    return _Prospects(
        tokens=tokens,
        cased_tokens=cased,
        pattern=re.compile("|".join(re.escape(t) for t in tokens), re.IGNORECASE) if tokens else None,
        cased_pattern=re.compile("|".join(re.escape(c) for c in cased)) if cased else None,
        name_cased_bounded_tokens=cased_bounded,
        name_cased_bounded_pattern=bounded(cased_bounded),
        product_tokens=products,
        product_cased_tokens=products_cased,
        product_pattern=bounded(products, re.IGNORECASE),
        product_cased_pattern=bounded(products_cased),
    )


PROSPECTS = _load_prospects()


def _guard_is_required() -> bool:
    """Has the caller DECLARED that this guard must actually run here?

    Read at call time rather than at import, so the tests below can exercise both answers without
    re-importing the module. Unset and falsey are the same answer, because the honest default for an
    outside clone of a public repository is to skip (see `_Prospects.skip`).
    """
    return os.environ.get(GUARD_REQUIRED_ENV, "").strip().lower() not in _FALSEY


def _require_prospects() -> _Prospects:
    if PROSPECTS.skip:
        if _guard_is_required():
            # The third state, added by ADR-0042. `skip` and `error` already separated "nobody
            # configured this" from "somebody configured it wrong". Neither covers the case that
            # actually bit: a run that was SUPPOSED to be armed, wasn't, and reported green.
            #
            # A skip is quieter than a failure, and quiet is the whole failure mode — a green suite
            # with its privacy guard never having run is read by everyone, including its author, as
            # proof the rule held. So an environment that claims to be armed does not get to skip.
            pytest.fail(
                f"{GUARD_REQUIRED_ENV} is set, so this guard MUST run — but it cannot:\n\n"
                f"{PROSPECTS.skip}\n\n"
                f"This is a failure and not a skip on purpose. {GUARD_REQUIRED_ENV} is the caller "
                f"saying 'I own the private packs repo, so a skip here means my configuration is "
                f"broken, not that this checkout is an outsider's.' Set {PACKS_DIR_ENV} to that "
                f"checkout, or unset {GUARD_REQUIRED_ENV} if this environment genuinely cannot "
                f"reach it."
            )
        pytest.skip(PROSPECTS.skip)
    if PROSPECTS.error:
        pytest.fail(PROSPECTS.error)
    return PROSPECTS


def _token_indices(count: int) -> range:
    """Parametrize over POSITIONS, never over the tokens themselves.

    A token used as a pytest id is printed by `-v`, by `--collect-only`, and into any CI log. The
    whole point of this cycle is that a prospect's name exists in one place; an index keeps it there.
    `range(1)` when the list is empty gives the test a body to run so it can skip or fail properly,
    rather than vanishing into an empty-parametrize pass.
    """
    return range(max(1, count))


def _tracked_files() -> list[str]:
    try:
        return subprocess.check_output(["git", "ls-files"], cwd=REPO_ROOT, text=True).splitlines()
    except (subprocess.CalledProcessError, FileNotFoundError):
        pytest.skip("not a git checkout")


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


# Imported evidence archives: model transcripts and the scores computed from them. Not authored here.
#
# The rule this guard enforces is that WE do not publish whose readiness we are measuring. It cannot be
# "no tracked file contains the string", because an archived transcript contains whatever the measured
# model said, and the model names third-party products in its example payloads — a reference pack's
# frozen runs mention an HR system by name inside a sample JSON body. That is not a disclosure of our
# queue; it is a quotation of someone else's documentation.
#
# The archives are also the evidence behind published numbers and are byte-frozen: redacting one to
# satisfy a guard would edit the record a result rests on, which is the one repair this project must
# never make. So the region is excluded, narrowly and by name, and its extent is asserted below so it
# cannot quietly grow into "and also the docs, and also that one comment".
#
# This exclusion was forced, not chosen: it appeared the moment the token list stopped being
# hand-written and started covering every target in the queue (ADR-0018).
# `PROVENANCE.md` is the one HAND-WRITTEN file in the region — a human's note recording where an
# archive came from — so it stays inside the scan. Everything else here is a transcript, a score file
# or a report generated from them.
_ARCHIVE_RE = re.compile(r"^packs/[^/]+/fixtures/imported/(?!.*PROVENANCE\.md$)")


def _is_imported_archive(rel: str) -> bool:
    return bool(_ARCHIVE_RE.match(rel))


def _scan_tracked(prospects: _Prospects) -> tuple[list[str], set[Path]]:
    """Scan every tracked file this project AUTHORED — including this one. Imported archives excluded."""
    offenders: list[str] = []
    scanned: set[Path] = set()
    for rel in _tracked_files():
        p = REPO_ROOT / rel
        if not p.is_file() or _is_imported_archive(rel):
            continue
        try:
            text = p.read_text(errors="ignore")
        except OSError:
            continue
        scanned.add(p.resolve())
        for i, line in enumerate(text.splitlines(), 1):
            if prospects.search(line):
                offenders.append(f"{rel}:{i}: {line.strip()[:80]}")
    return offenders, scanned


def test_public_repo_names_no_prospect():
    """No tracked file names a measured prospect. No file is exempt — not even this one."""
    prospects = _require_prospects()
    offenders, _ = _scan_tracked(prospects)
    assert not offenders, (
        "the public repo must name no measured prospect (they live in the private packs repo); found:\n"
        + "\n".join(offenders)
    )


def test_the_archive_exclusion_covers_archives_and_nothing_else():
    """Pin the one excluded region, so "we author it" cannot drift into "it is inconvenient".

    An exempt region is how this guard failed before: the old version excused exactly one file — its
    own — and that file became the roster. The replacement excuses a region too, so the region has to
    be bounded by a test rather than by a comment. Every path it excludes must be an imported evidence
    archive; a doc, an ADR, a task file or a source file must never be excluded, whatever it contains.
    """
    tracked = _tracked_files()
    excluded = [rel for rel in tracked if _is_imported_archive(rel)]
    assert excluded, "the archive exclusion matches nothing — it is dead, or the layout moved"
    for rel in excluded:
        assert "/fixtures/imported/" in rel, f"{rel} is not an imported archive"
    # Authored content is never excluded, wherever it sits. PROVENANCE.md lives inside the archive
    # directory but is written by a human about the archive, so it stays in the scan.
    for rel in tracked:
        if (rel.startswith(("docs/", "core/"))
                or "/tasks/" in rel
                or rel.endswith(("PROVENANCE.md", "pack.yaml", "specs.yaml", "docs-manifest.yaml"))
                or "/" not in rel):
            assert not _is_imported_archive(rel), f"{rel} must never be excluded from the leak scan"
    assert any(r.endswith("PROVENANCE.md") for r in tracked), "expected a hand-written provenance note"


def test_the_guard_does_not_exempt_its_own_file():
    """The exemption that used to be here is the hazard this design removed; keep it removed.

    While the tokens were literals, this file had to be skipped by its own scan, and so the single
    tracked file excused from the no-names rule was the one place all the names were written down.
    With the list loaded from outside the repository there is nothing left to excuse. Asserting the
    file is genuinely in the scanned set means a future 'just skip this one file' cannot come back
    quietly — it has to fail a test that says why.
    """
    prospects = _require_prospects()
    _, scanned = _scan_tracked(prospects)
    assert Path(__file__).resolve() in scanned, (
        "the leak guard must scan its own source like any other tracked file"
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
    prospects = _require_prospects()
    try:
        refs = subprocess.check_output(
            ["git", "for-each-ref", "--format=%(refname)", "refs/heads", "refs/remotes"],
            cwd=REPO_ROOT, text=True,
        ).splitlines()
    except (subprocess.CalledProcessError, FileNotFoundError):
        pytest.skip("not a git checkout")
    offenders = [r for r in refs if prospects.search(r)]
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


def test_prospect_tokens_are_derived_from_the_private_queue():
    """The list comes from the authoritative source, so a queued target cannot go unguarded.

    This is the gate on the hazard that used to read "the token list can omit a prospect". While the
    tokens were hand-maintained literals, a target could enter the private queue and simply be
    forgotten here — and it happened, between cycles 2 and 6. Derived from `queue.yaml` plus the pack
    directories, forgetting is no longer possible: the same file that adds a target adds its tokens.

    What this still cannot do, said plainly: it holds only where the private repo is reachable. Where
    `AIRE_PACKS_DIR` is unset the guard skips, and a skip is quieter than a failure. That residue is
    registered as its own ungated hazard rather than implied by this test passing.
    """
    prospects = _require_prospects()
    assert prospects.tokens or prospects.cased_tokens, "derived an empty name list"
    # Names are counted, never printed: a failure message must not become the roster either.
    assert not any(t.strip() != t for t in prospects.tokens), "a derived token has stray whitespace"


@pytest.mark.parametrize("index", _token_indices(len(PROSPECTS.tokens)))
def test_prospect_regex_actually_matches_every_token_it_claims(index):
    """Guard the guard, prospect side — the equivalent of the vendor-token check above.

    Its absence was noticed the ordinary way: removing one token from the pattern on purpose left the
    ref scan failing anyway, because a DIFFERENT token still matched the same ref. A break test that
    cannot fail for the reason you intended proves nothing, so each token is asserted on its own.

    Parametrized over positions rather than tokens, so `pytest -v` prints indices instead of names.
    """
    prospects = _require_prospects()
    token = prospects.tokens[index]
    assert prospects.pattern.search(f"cycle-09-{token}"), f"token #{index} is listed but never fires"
    assert prospects.pattern.search(f"prefix {token.upper()} suffix"), \
        f"token #{index} is case-sensitive but was not declared cased"


@pytest.mark.parametrize("index", _token_indices(len(PROSPECTS.cased_tokens)))
def test_cased_prospect_regex_fires_on_the_proper_noun_only(index):
    """Both halves of the bargain a cased token is given.

    A cased token buys leniency on ordinary prose — it exists because the name is also a common word,
    and a guard that fires on ordinary prose gets routed around. So it has to pay for that leniency:
    it must still fire on the proper noun, and it must still stay silent on the lowercase word.
    """
    prospects = _require_prospects()
    token = prospects.cased_tokens[index]
    assert prospects.cased_pattern.search(f"cycle-06-{token}"), \
        f"cased token #{index} is listed but never fires"
    assert not prospects.cased_pattern.search(f"prefix {token.lower()} suffix"), \
        f"cased token #{index} is cased-only precisely so the lowercase word does not fire"


# ------------------------- a name short enough to sit inside an ordinary word (ADR-0049) ---
#
# ADR-0028 made NAME tokens unbounded on an argument that is sound for a coined name — it is
# distinctive, so over-matching it is free, and it buys `<name>-api` and `<name>'s` for nothing. The
# argument fails for a short acronym, which is an ordinary way for a company to be known and which
# sits inside ordinary words. An unbounded three-letter token fires on innocent prose, and this
# guard's own source says a guard that cries wolf is a guard someone turns off.
#
# The mechanism below is therefore opt-in PER TOKEN. Every existing declaration keeps the unbounded
# behaviour it was written for; only a token whose entry names it in `guard_tokens_cased_whole_word`
# becomes bounded.
#
# These tests build a SYNTHETIC queue and run it through the real `_load_prospects`. Two reasons.
# Mirroring the loader's logic in a fixture would let the fixture pass while the loader is broken.
# And the opt-in list is legitimately empty for almost every target, so tests parametrized over the
# real list would go vacuous the moment no target used it — the cycle-18 failure shape. Coverage of
# the mechanism must not depend on anyone having opted in.
#
# `ART` is a neutral stand-in with the property under test: it sits inside CHARTER, SMART and PARTY.
# It is not anybody's name, which is the point — this file names nobody.

_SYNTHETIC_QUEUE = """\
targets:
- id: bounded-example
  display_name: Bounded Example
  status: queued
  guard_tokens: [artglobal]
  guard_tokens_cased_whole_word: [ART]
  guard_product_tokens: [examplecoined]
- id: unbounded-example
  display_name: Unbounded Example
  status: queued
  guard_tokens: []
  guard_tokens_cased: [XYZ]
  guard_product_tokens: [othercoined]
"""


@pytest.fixture
def synthetic_prospects(tmp_path, monkeypatch):
    """A real `_load_prospects` over a queue we control, so the loader itself is under test."""
    (tmp_path / "queue.yaml").write_text(_SYNTHETIC_QUEUE)
    monkeypatch.setenv(PACKS_DIR_ENV, str(tmp_path))
    monkeypatch.setenv(QUEUE_ENV, str(tmp_path / "queue.yaml"))
    prospects = _load_prospects()
    assert not prospects.skip and not prospects.error, prospects.skip or prospects.error
    assert prospects.name_cased_bounded_tokens == ["ART"], (
        "the synthetic queue's opt-in did not survive the loader, so every assertion below would be "
        "testing an empty pattern"
    )
    return prospects


@pytest.mark.parametrize("word", ["CHARTER", "SMART", "PARTY", "ARTICLE", "STARTED"])
def test_an_opted_in_token_stops_firing_inside_a_longer_word(synthetic_prospects, word):
    """The false positive the opt-in exists to stop. Unbounded, every one of these is a hit."""
    assert not synthetic_prospects.name_cased_bounded_pattern.search(word), \
        f"{word!r} matched a whole-word token; the \\b boundary is gone"
    assert not synthetic_prospects.search(word), \
        f"{word!r} still reaches the guard by some other pattern"


@pytest.mark.parametrize("text", [
    "ART",                       # the bare proper noun
    "the ART surface",
    "ART-api",                   # the hyphen form unbounded matching used to buy
    "ART's developer portal",    # the possessive
    "cycle-37-ART",              # a branch name, which is how this class of leak got published
    "(ART)",
])
def test_an_opted_in_token_still_fires_where_it_must(synthetic_prospects, text):
    """The true positive. Bounding must cost the false hits and nothing else — `\\b` sits between a
    letter and a hyphen, an apostrophe or a bracket, so every form ADR-0028 wanted survives."""
    assert synthetic_prospects.name_cased_bounded_pattern.search(text), \
        f"{text!r} must still be caught; bounding was meant to cost false positives only"
    assert synthetic_prospects.search(text), f"{text!r} did not reach the guard at all"


def test_the_compound_case_is_lost_and_a_companion_token_covers_it(synthetic_prospects):
    """The honest half, asserted in one place so the cost cannot be quietly forgotten.

    Whole-word matching CANNOT see a name inside a compound — a hostname is the case that matters,
    because a docs host is exactly where a leak lands. That is a real loss against the unbounded
    behaviour, and it is not repaired by the boundary rule; it is repaired at the declaration site,
    by the entry also declaring the compound as its own insensitive token.

    Both halves are asserted together on purpose. Assert only the first and the guard looks broken;
    assert only the second and the loss disappears from the record.
    """
    host = "developer.artglobal.com"
    assert not synthetic_prospects.name_cased_bounded_pattern.search(host.upper()), \
        "whole-word matching is not expected to reach inside a compound — if it does, this test is stale"
    assert synthetic_prospects.search(host), (
        "the compound is not covered by anything. An entry that opts a name into whole-word matching "
        "must also declare the compound form (a hostname, a squashed brand) as an insensitive token, "
        "or the guard is strictly weaker than it was before the opt-in."
    )


def test_an_opted_in_token_is_still_cased_only(synthetic_prospects):
    """It buys the same leniency a cased token buys, and pays the same price."""
    assert not synthetic_prospects.name_cased_bounded_pattern.search("the art of it"), \
        "the lowercase ordinary word must not fire"
    assert synthetic_prospects.name_cased_bounded_pattern.search("ART"), \
        "...but the proper noun still must"


def test_an_unbounded_name_token_is_left_exactly_as_it_was(synthetic_prospects):
    """The opt-in is per token. A target that did not ask for bounding must not receive it.

    This is what makes the change safe to land against a queue full of existing declarations: their
    behaviour is unchanged, including the substring matching some of them rely on.
    """
    assert synthetic_prospects.cased_pattern.search("XYZZY"), (
        "a cased token that did NOT opt in must still match inside a longer word — bounding leaked "
        "across to entries that never asked for it"
    )
    assert "XYZ" not in synthetic_prospects.name_cased_bounded_tokens


def test_declaring_a_token_bounded_and_unbounded_at_once_is_refused(tmp_path):
    """An opt-in the unbounded list silently overrides is worse than no opt-in.

    Both patterns are consulted by `search`, so the unbounded one wins every race between them. An
    entry listing the same token in both would read as bounded in review and behave as unbounded in
    fact — the exact failure this field removes, wearing the label of the fix. So it is a parse
    error, in the same place and for the same reason an unknown status is one.
    """
    from core.factory import QueueEntry, load_queue
    bad = tmp_path / "queue.yaml"
    bad.write_text(
        "targets:\n"
        "- id: contradictory\n"
        "  status: queued\n"
        "  guard_tokens_cased: [ART]\n"
        "  guard_tokens_cased_whole_word: [ART]\n"
    )
    with pytest.raises(ValueError) as excinfo:
        load_queue(bad)
    assert "ART" in str(excinfo.value) and "guard_tokens_cased_whole_word" in str(excinfo.value), \
        "the error must name the token and both fields, or it cannot be acted on"
    # and the accessor refuses on its own, for a caller that built the entry some other way
    with pytest.raises(ValueError):
        QueueEntry(id="x", guard_tokens_cased=["ART"],
                   guard_tokens_cased_whole_word=["ART"]).leak_guard_bounded_name_tokens()


def test_the_bounded_name_field_round_trips_through_a_save(tmp_path):
    """It must survive `to_dict`, or a dispatcher writing the queue back would silently drop the
    opt-in and restore the unbounded behaviour on the next load."""
    from core.factory import QueueEntry, load_queue, save_queue
    entry = QueueEntry(id="bounded-example", guard_tokens=["artglobal"],
                       guard_tokens_cased_whole_word=["ART"])
    assert entry.to_dict()["guard_tokens_cased_whole_word"] == ["ART"]
    path = tmp_path / "queue.yaml"
    save_queue(path, [entry])
    assert load_queue(path)[0].leak_guard_bounded_name_tokens() == ["ART"]
    # omitted where empty, like its four siblings — a queue file gains no noise from this field
    assert "guard_tokens_cased_whole_word" not in QueueEntry(id="plain").to_dict()


@pytest.mark.parametrize("index", _token_indices(len(PROSPECTS.name_cased_bounded_tokens)))
def test_every_real_opted_in_token_fires_on_its_proper_noun_only(index):
    """Per-token coverage of the REAL list, alongside the mechanism tests above.

    This one is allowed to be empty — opting in is a deliberate per-target choice, so asserting the
    list is non-empty would make removing the last opted-in target a build failure. The mechanism's
    own coverage does not depend on this test having anything to iterate, which is what keeps the
    empty case honest rather than vacuous.
    """
    prospects = _require_prospects()
    if not prospects.name_cased_bounded_tokens:
        pytest.skip("no target has opted a name token into whole-word matching")
    token = prospects.name_cased_bounded_tokens[index]
    assert prospects.name_cased_bounded_pattern.search(f"cycle-37-{token}"), \
        f"bounded token #{index} is listed but never fires"
    assert not prospects.name_cased_bounded_pattern.search(f"prefix {token.lower()} suffix"), \
        f"bounded token #{index} is cased-only precisely so the lowercase word does not fire"
    assert not prospects.name_cased_bounded_pattern.search(f"un{token}ed"), \
        f"bounded token #{index} matched inside a longer word; the \\b boundary is gone"


def test_the_product_token_list_is_not_empty():
    """Non-vacuity, the cycle-18 standing rule: a gate that measures nothing is worse than none.

    Every declared target sells something, so an empty product list means the queue was never
    annotated (or the fields were dropped in a save) and this whole guard passes green while matching
    nothing. It must fail loudly instead, because the failure it is meant to catch — a public file
    naming a vendor by its products (issue #40) — looks exactly the same as success from here.
    """
    prospects = _require_prospects()
    assert prospects.tokens, "no name tokens loaded"
    assert prospects.cased_tokens or prospects.tokens, "no name tokens loaded"
    assert prospects.product_pattern or prospects.product_cased_pattern, (
        "no product tokens loaded from the queue, so the product half of this guard matches nothing "
        "and would pass green over a file naming every product of every target"
    )


@pytest.mark.parametrize("index", _token_indices(len(PROSPECTS.product_tokens)))
def test_product_regex_fires_on_the_product_name(index):
    prospects = _require_prospects()
    token = prospects.product_tokens[index]
    assert prospects.product_pattern.search(f"the {token} surface"), \
        f"product token #{index} is listed but never fires"
    assert prospects.product_pattern.search(f"the {token.upper()} surface"), \
        f"product token #{index} is case-sensitive but was not declared cased"


@pytest.mark.parametrize("index", _token_indices(len(PROSPECTS.product_cased_tokens)))
def test_cased_product_regex_fires_on_the_proper_noun_only(index):
    """Same bargain the cased NAME tokens strike, and it matters more here: a product is far more
    likely than a company to be named with ordinary technical English."""
    prospects = _require_prospects()
    token = prospects.product_cased_tokens[index]
    assert prospects.product_cased_pattern.search(f"the {token} surface"), \
        f"cased product token #{index} is listed but never fires"
    assert not prospects.product_cased_pattern.search(f"the {token.lower()} surface"), \
        f"cased product token #{index} is cased-only precisely so the lowercase words do not fire"


@pytest.mark.parametrize("index", _token_indices(len(PROSPECTS.product_tokens)))
def test_a_product_token_does_not_fire_inside_a_longer_word(index):
    """The boundary rule that makes product tokens usable at all, pinned per token.

    Without it this guard is not merely noisy, it is unusable — its first run reported eight false
    positives against one true one, every false one a product token sitting inside a longer ordinary
    word. Suffixing a letter is the cheapest expression of that, and it must stay silent.
    """
    prospects = _require_prospects()
    token = prospects.product_tokens[index]
    assert not prospects.product_pattern.search(f"the {token}ing surface"), \
        f"product token #{index} matched inside a longer word; the \\b boundary is gone"


def test_the_prospect_matcher_does_not_fire_on_unrelated_text():
    """Negative control, written with no name in it — which is now possible.

    A matcher assembled from a list loaded at runtime could go wrong in the direction that matters
    least visibly: matching everything. Then every tracked file is an offender and someone "fixes"
    the guard by loosening it. This asserts the boring half — ordinary prose stays clean.
    """
    prospects = _require_prospects()
    for benign in ("the runner scores six dimensions",
                   "a 2xx with an empty body is a fetch failure",
                   "cycle-99-example-target-that-is-not-real"):
        assert not prospects.search(benign), f"the matcher fires on unrelated text: {benign!r}"


# ------------------------------------------- arming the guard where it has no excuse (ADR-0042) ---
#
# The hazard `guard-skips-where-the-private-repo-is-absent` records the trade ADR-0018 made: the name
# list lives outside this repository, so the guard skips wherever `AIRE_PACKS_DIR` is unset, and a
# skipped guard reports green. That entry named its own fix in `fix_queued_to` — "if this project ever
# gains CI, requiring the variable there, and failing without it" — and this is that.
#
# It is deliberately NOT a change of default. An outside clone still skips, because failing there
# would break a public repository's suite for a reason unrelated to its own tree. What changes is that
# an environment CAN declare itself armed, and a declared-armed environment that skips fails the build.


@pytest.mark.parametrize("value", ["", "0", "false", "FALSE", "no", "off", "  "])
def test_a_falsey_or_absent_declaration_leaves_the_skip_a_skip(monkeypatch, value):
    """The default must stay a skip: an outside clone is not misconfigured, it is an outsider."""
    monkeypatch.delenv(GUARD_REQUIRED_ENV, raising=False)
    assert not _guard_is_required(), "unset must mean not-required"
    monkeypatch.setenv(GUARD_REQUIRED_ENV, value)
    assert not _guard_is_required(), f"{value!r} must mean not-required"


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "required"])
def test_any_other_declaration_arms_the_guard(monkeypatch, value):
    monkeypatch.setenv(GUARD_REQUIRED_ENV, value)
    assert _guard_is_required()


def test_a_declared_requirement_turns_the_skip_into_a_failure(monkeypatch):
    """The whole point: where the guard is declared required, "it did not run" is a red build.

    Verified by breaking it — with the promotion removed this raises Skipped, and a skip is what CI
    reads as success.
    """
    monkeypatch.setenv(GUARD_REQUIRED_ENV, "1")
    monkeypatch.setattr(
        sys.modules[__name__], "PROSPECTS",
        _Prospects(skip="the name list could not be loaded in this environment"),
    )
    with pytest.raises(pytest.fail.Exception) as excinfo:
        _require_prospects()
    message = str(excinfo.value)
    assert GUARD_REQUIRED_ENV in message and PACKS_DIR_ENV in message, (
        "the failure must name both variables, or the person reading a CI log cannot act on it"
    )
    assert "the name list could not be loaded" in message, "the original reason must survive"


def test_without_the_declaration_the_same_state_is_still_a_skip(monkeypatch):
    """The other half of the same bargain, so the promotion cannot quietly become unconditional."""
    monkeypatch.delenv(GUARD_REQUIRED_ENV, raising=False)
    monkeypatch.setattr(
        sys.modules[__name__], "PROSPECTS",
        _Prospects(skip="the name list could not be loaded in this environment"),
    )
    with pytest.raises(pytest.skip.Exception):
        _require_prospects()


@pytest.mark.parametrize("required", ["1", ""])
def test_a_configured_but_broken_source_fails_either_way(monkeypatch, required):
    """`error` already outranked `skip`; arming must not have disturbed that ordering.

    A typo'd `AIRE_PACKS_DIR` was always a failure and not a skip — that is the older half of this
    design — and it stays one whether or not the run declares itself armed.
    """
    monkeypatch.setenv(GUARD_REQUIRED_ENV, required)
    monkeypatch.setattr(
        sys.modules[__name__], "PROSPECTS",
        _Prospects(error="it is not a directory"),
    )
    with pytest.raises(pytest.fail.Exception) as excinfo:
        _require_prospects()
    assert "not a directory" in str(excinfo.value)


def test_an_armed_run_here_is_actually_armed():
    """Non-vacuity for THIS run: if the suite declares itself armed, prove the list really loaded.

    Without this, every assertion above is about a synthetic `_Prospects`, and the real one could
    still be a skip. It is inert where the declaration is absent, which is what keeps an outside
    clone green.
    """
    if not _guard_is_required():
        pytest.skip(f"{GUARD_REQUIRED_ENV} not declared; the guard is allowed to skip here")
    assert not PROSPECTS.skip, PROSPECTS.skip
    assert not PROSPECTS.error, PROSPECTS.error
    assert PROSPECTS.tokens, "armed, but the derived name list is empty"


def test_the_ref_scan_saw_more_than_the_branch_it_is_standing_on():
    """Non-vacuity for the REF half, which is the half a shallow checkout silently empties.

    `test_public_repo_ref_names_no_prospect` is only as good as the refs present. A CI runner cloned
    at `fetch-depth: 1` has exactly one, so the scan passes by having nothing to look at — the same
    vacuous-pass shape as an empty parametrize, reached by a different route. The workflow therefore
    clones at depth 0, and this asserts the clone actually delivered.

    Inert unless armed, because a legitimate fresh single-branch clone is not a misconfiguration.
    """
    if not _guard_is_required():
        pytest.skip(f"{GUARD_REQUIRED_ENV} not declared; a shallow checkout is nobody's problem here")
    try:
        refs = subprocess.check_output(
            ["git", "for-each-ref", "--format=%(refname)", "refs/heads", "refs/remotes"],
            cwd=REPO_ROOT, text=True,
        ).splitlines()
    except (subprocess.CalledProcessError, FileNotFoundError):
        pytest.fail("armed, but this is not a git checkout, so the ref scan cannot run at all")
    assert len(refs) > 1, (
        f"the ref scan saw {len(refs)} ref(s). Armed, that means a shallow or single-branch clone, "
        f"and the scan is passing because it has nothing to read rather than because the refs are "
        f"clean. Clone with full depth (`fetch-depth: 0` in Actions)."
    )
