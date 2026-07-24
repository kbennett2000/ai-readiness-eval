# ADR-0003: The job-category taxonomy for cross-vendor comparison

## Status
Accepted

## Context
The eval measures each vendor with **product-native** tasks — the everyday jobs an integrator actually
does with *that* product, phrased the way a developer would type them into an AI tool. Product-native
tasks are what make the measurement honest, but they are not directly comparable across vendors: one
product's "aggregate a source" is another's "connect a directory." To say anything cross-vendor we need
a shared axis that sits *above* the tasks and names no product.

## Decision

### A canonical set of job categories
A fixed, ordered set of vendor-neutral job categories lives in `core/taxonomy.py` (`CATEGORIES`). It was
derived from the reference pack's 11 tasks and is intended to fit any enterprise identity/API product:

`authenticate`, `find-principal`, `list-principal-accounts`, `grant-access`, `revoke-access`,
`search-filter`, `audit-report`, `connect-source`, `policy-object-create-and-test`, `review-campaign`,
`event-subscription`.

The order is the natural integrator arc: authenticate → read → change access → observe/govern. The set
grows only by amending this ADR, never ad hoc.

### Every task declares one category
Each task file carries a `job_category` field (validated against `CATEGORIES` by `core/validate.py`),
**distinct from** the existing `category` field, which is a difficulty tier
(`foundational`/`daily-automation`/`multi-step`). Tasks stay product-native; only the category is shared.

### Comparison is category-level only
Cross-vendor comparison happens at the category level. A vendor's raw per-task scores are never compared
to another vendor's per-task scores — only the per-category rollups are. Within a vendor, tasks remain
the unit of measurement and reporting.

### N/A is a first-class outcome
A category with no natural product-native job for a given vendor is marked N/A in that pack's `pack.yaml`
(`na_categories: {category: reason}`), and the validator forbids a task from mapping to an N/A category.
An N/A is a finding about the product's surface, recorded, not hidden.

### Retro-map of the reference pack (1:1)

| category | reference-pack task |
|---|---|
| authenticate | auth-token |
| find-principal | find-identity |
| list-principal-accounts | identity-accounts |
| grant-access | access-request |
| revoke-access | grant-revoke |
| search-filter | search-filter |
| audit-report | audit-report |
| connect-source | source-aggregation |
| policy-object-create-and-test | transform |
| review-campaign | cert-campaign |
| event-subscription | lifecycle-trigger |

## Consequences
- Cross-vendor reporting has a stable, product-neutral axis, while per-vendor reporting stays
  product-native.
- `core/validate.py` enforces the taxonomy: an unknown or N/A `job_category` fails the pack before any
  ground truth is trusted.
- Adding a category is a deliberate, reviewable act (an ADR amendment), so the comparison axis does not
  drift silently as packs are added.
- `job_category` is inert to scoring — it changes no measurement; the regression gate confirms the
  reference-pack tables are unmoved by its addition.
