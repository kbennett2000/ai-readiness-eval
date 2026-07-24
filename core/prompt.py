"""The fixed answer-block instruction suffix (single source of truth).

Every condition appends this to the task prompt so the scorer has a stable,
machine-parseable contract to read (ADR-0004). Keep the example minimal and the
key set exactly aligned with what `answer_block.parse` expects and what `scorer`
consumes: endpoints[method, path, api_version], auth_flow, required_scopes,
key_parameters.
"""
from __future__ import annotations

ANSWER_BLOCK_LANG = "answer-summary"

ANSWER_BLOCK_SUFFIX = """\

---

After your normal answer (code and explanation), end your response with a single fenced code \
block tagged `answer-summary` containing YAML with exactly these keys:

  endpoints:            # one entry per distinct API call your answer uses
    - method:           # HTTP method, e.g. GET, POST
      path:             # request path only — no scheme/host/tenant, no query string;
                        # use {braces} for path parameters, e.g. /v3/accounts/{id}
      api_version:      # the version segment: v3, beta, oauth, v2025, or <service>/v1
  auth_flow:            # short phrase naming the auth mechanism, e.g. "OAuth2 bearer token"
  required_scopes:      # list of OAuth scope strings ([] if none)
  key_parameters:       # list of the key parameter/body-field NAMES (strings)

Example:

```answer-summary
endpoints:
  - method: GET
    path: /v3/widgets
    api_version: v3
auth_flow: OAuth2 bearer token
required_scopes: [widgets:read]
key_parameters: [filters]
```

Output the `answer-summary` block exactly once, as the very last thing in your response.
"""


def build_prompt(task_prompt: str) -> str:
    """Return the task prompt with the fixed answer-block contract appended."""
    return task_prompt.rstrip() + "\n" + ANSWER_BLOCK_SUFFIX
