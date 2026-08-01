"""The canonical job-category taxonomy (ADR-0003).

Tasks stay product-native; cross-vendor comparison happens only at the category level. Each task in a
pack declares a `job_category` from this set. A pack may mark a category not-applicable for its product
(in `pack.yaml: na_categories`) with a one-line reason — an N/A is itself a finding.

This module names no vendor. The set was derived from the reference pack's 11 tasks and is intended to
fit any enterprise identity/API product; it grows by ADR, not ad hoc.
"""
from __future__ import annotations

# Ordered canonical categories. The order is the natural integrator arc: authenticate, then read, then
# change access, then observe/govern.
CATEGORIES: tuple[str, ...] = (
    "authenticate",                    # obtain/exchange credentials for an API token
    "find-principal",                  # look up a user/identity/principal
    "list-principal-accounts",         # a principal's linked accounts / app assignments / memberships
    "grant-access",                    # request or assign access (entitlement, app, group, role)
    "revoke-access",                   # remove access
    "search-filter",                   # query a collection with a filter/expression
    "audit-report",                    # pull audit events / logs / a report
    "connect-source",                  # configure/aggregate an identity source or connector
    "policy-object-create-and-test",   # create and validate a config/policy/transform object
    "review-campaign",                 # run/inspect an access review or certification campaign
    "event-subscription",             # subscribe to events / triggers / webhooks
)

# The docs cohort's own arc (ADR-0044). A vendor's manuals are not an identity API, and every
# category above would have to be marked n/a for a pack whose questions are "which part", "will
# these two revisions work together" and "what do I need to upgrade to". Nine n/a lines arguing that
# a controller manual has no access-review concept would be a fiction dressed as a finding, so the
# docs cohort declares the arc it actually has: choose a part, check a combination, plan a move,
# replace a part. Same rule as above — it grows by ADR, not ad hoc.
DOCS_CATEGORIES: tuple[str, ...] = (
    "select-hardware",          # name the part that meets a stated requirement
    "verify-compatibility",     # will this firmware / software / hardware combination work
    "plan-revision-upgrade",    # which revision is required to gain a capability
    "identify-replacement",     # the successor or variant part for one that is stated
)

_CATEGORY_SET = frozenset(CATEGORIES)
_DOCS_CATEGORY_SET = frozenset(DOCS_CATEGORIES)

#: Every category name in the project, by cohort. `validate` reads this rather than a constant, so a
#: task cannot declare a category belonging to the other cohort's arc.
BY_COHORT: dict[str, tuple[str, ...]] = {"api": CATEGORIES, "docs": DOCS_CATEGORIES}


def is_category(name: str) -> bool:
    return name in _CATEGORY_SET


def is_docs_category(name: str) -> bool:
    return name in _DOCS_CATEGORY_SET
