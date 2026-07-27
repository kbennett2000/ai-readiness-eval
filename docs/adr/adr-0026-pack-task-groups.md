# ADR-0026 — A pack may declare task groups, and the report renders them

**Status:** Accepted
**Date:** 2026-07-27
**Extends:** ADR-0003 (job-category taxonomy), ADR-0004 (category rollup renderer).

## Context

Every number this project publishes is currently sliced two ways: by **dimension** (the six of
ADR-0002) and by **job category** (the eleven of ADR-0003). Both are fixed, shared vocabularies —
that is the point of them, because they are what makes packs comparable across vendors.

A vendor cycle now asks a question neither slice can express. The next queued target is a platform
whose API surface accreted over roughly eight years — several subsystems shipped in 2018–2019, and
several more between 2022 and late 2023. The hypothesis under test is that **accuracy tracks how long
a surface has existed**: that a model knows the older subsystems from its weights and the newer ones
not at all.

That grouping is real, it is the finding the cycle exists to produce, and it fits nowhere:

- It is **not a job category.** Two tasks that create an object are both
  `policy-object-create-and-test` whether the object is eight years old or two; the taxonomy is what
  makes them comparable across vendors and must not be bent to carry a per-vendor axis.
- It is **not a task field.** The task schema is `additionalProperties: False` on purpose. More
  importantly, the same tasks can be grouped more than one way, and a grouping is an **argument a
  card makes**, not a fact a task file carries.
- Computing it **by hand in the card** was the option this project has already learned to refuse.
  Cycle 19's entire finding was that hand-maintained derived numbers go stale silently while the
  gated ones stay right — six derived files across three packs were publishing figures their own
  `scores.json` had withdrawn.

## Decision

A pack may declare named task groups in `pack.yaml`, beside `expected_task_ids`:

```yaml
task_groups:
  long-stable:
    label: "Long-stable surfaces"
    rationale: "First-party release notes date every subsystem in this group to 2018-2019,
                well before the measured model's training window closes. <links>"
    tasks: [task-a, task-b, task-c, …]
  newer:
    label: "Newer surfaces"
    rationale: "First-party release notes date these to 2022-2023, at or after the edge of
                that window. <links>"
    tasks: [task-d, task-e, task-f, …]
```

Optional, absent from every existing pack, and inert when absent — **no published number moves.**

### The arithmetic is the arithmetic that already existed

`category.rollup_by_category` already computed exactly this: per-dimension means over a set of tasks,
driven by a `task_id -> key` map. It was only hardcoded to iterate the taxonomy. So the generic
`rollup_by_group(aggregate, task_to_group, groups, na_groups=None)` is **extracted**, and
`rollup_by_category` becomes a thin wrapper over it.

That is not tidiness. It means "the mean of a group" cannot be computed two different ways inside one
report — a pack's surface-age table and the shared job-category table are the same function. A test
asserts the wrapper still produces output identical to the direct call.

### The split is generated, never typed

`core compare --by-group` renders it, so the group table is a build product like every other results
file. `render_group_comparison_md` prints, per group: the six dimensions under both conditions, the
gap, the task list, **and the rationale**.

### Four validator rules, because a reporting axis must partition the pack

When `task_groups` is present:

1. every named task must exist;
2. every task must be in **exactly one** group;
3. no group may be empty;
4. every group must carry a **rationale**.

Rules 1–3 exist because a group split that silently dropped or double-counted a task would publish a
per-group mean no reader could reconstruct from the per-task table beside it — and dropping is the
direction that *flatters*, since it lets a bad task vanish from both rows. Each rule was verified by
breaking the implementation and watching the corresponding test fail.

## What this cannot check, and it is the important part

**Nothing here can verify that a group is TRUE of the world.** No test can confirm that "long-stable"
describes the Jobs API, or that a surface shipped when a card says it did. The `rationale` field is
required precisely because it is the only thing a reviewer can disagree with — it is evidence, not
decoration, which is why an empty one **blocks** rather than drawing a note.

A pack could therefore assemble two groups that make its headline look like a finding. The defences
are that the grouping is committed in `pack.yaml` **before the grid runs**, that the per-task table
is published beside the group table, and that the rationale must cite first-party dating. Those are
real but partial, and this is recorded as an ungated hazard rather than claimed as solved.

A second, subtler failure this does not prevent: two groups that differ in **task mix** rather than
in the property being tested. If the "newer" group happened to hold the harder tasks, the split would
measure difficulty and be reported as surface age. The mitigation belongs to the pack, not to core —
groups must be matched on task `category` and as far as possible on `job_category`, and the card must
say so — but core cannot enforce it, and the hazard entry says that plainly.

## Consequences

- Additive and optional; every existing pack validates and scores unchanged.
- One rollup implementation instead of two.
- A pack can now publish an axis of its own without inventing a private renderer or hand-computing a
  number — the failure mode cycle 19 spent itself correcting.
