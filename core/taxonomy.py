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

_CATEGORY_SET = frozenset(CATEGORIES)


def is_category(name: str) -> bool:
    return name in _CATEGORY_SET
