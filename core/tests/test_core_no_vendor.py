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


@dataclass
class _Prospects:
    """The name list, loaded from outside this repository — or the reason there isn't one."""
    tokens: list[str] = field(default_factory=list)          # matched case-insensitively
    cased_tokens: list[str] = field(default_factory=list)    # matched exactly as written
    pattern: re.Pattern | None = None
    cased_pattern: re.Pattern | None = None
    skip: str = ""      # set => the private repo is not configured; skipping is correct
    error: str = ""     # set => it IS configured and is broken; that must be loud, never a skip

    def search(self, text: str) -> bool:
        return bool((self.pattern and self.pattern.search(text))
                    or (self.cased_pattern and self.cased_pattern.search(text)))


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
    for entry in entries:
        ins, cas = entry.leak_guard_tokens()
        tokens += ins
        cased += cas
    queue_ids = {e.id for e in entries}
    for pack_yaml in sorted(root.glob("*/pack.yaml")):
        name = pack_yaml.parent.name
        if name in queue_ids:
            continue
        collapsed = re.sub(r"[-_\s]+", "", name)
        tokens += [name] + ([collapsed] if collapsed != name else [])

    tokens = list(dict.fromkeys(t for t in tokens if t.strip()))
    cased = list(dict.fromkeys(c for c in cased if c.strip()))
    if not tokens and not cased:
        return broken("it yielded no names at all, so the guard would match nothing and pass green")
    return _Prospects(
        tokens=tokens,
        cased_tokens=cased,
        pattern=re.compile("|".join(re.escape(t) for t in tokens), re.IGNORECASE) if tokens else None,
        cased_pattern=re.compile("|".join(re.escape(c) for c in cased)) if cased else None,
    )


PROSPECTS = _load_prospects()


def _require_prospects() -> _Prospects:
    if PROSPECTS.skip:
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
