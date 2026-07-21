# Policy rule files

This directory holds the declarative rules for the Adaptive Policy Pattern
(`docs/ARCHITECTURE.md`) — one YAML file per policy, loaded and evaluated by
`core.policy_engine.evaluate_policy()`. No policy's strategy selection lives
in Python code; it lives here.

Named policies (per `docs/ARCHITECTURE.md`): `ParserPolicy`, `ChunkingPolicy`,
`EmbeddingPolicy`, `LanguagePolicy`, `QueryPolicy`, `RerankPolicy`,
`CachePolicy`, `ContextPolicy`, `PromptPolicy`, `ModelRouter`,
`GuardrailProfile`. Each is retrofitted in its own phase
(`docs/RETROFIT-AUDIT.md`'s backlog) — this directory is scaffolding only as
of the Phase 0 retrofit; no concrete `<policy_name>.yaml` files exist here
yet. A missing file is a normal, expected state to the engine (it safely
falls back), not an error.

## File shape: `config/policies/<policy_name>.yaml`

```yaml
policy: <policy_name>
version: "1"
rules:
  - name: <rule_id>              # a unique, human-readable rule name
    when:
      <signal_name>: { <comparator>: <value> }
      <signal_name_2>: { <comparator>: <value> }
      # every condition in `when` must hold (AND) for the rule to match
    then:
      <outcome_key>: <outcome_value>
      # arbitrary key/value payload - shape is defined by whichever
      # concrete policy this file belongs to, not by the engine itself
  - name: <another_rule>
    when: { ... }
    then: { ... }
fallback:
  <outcome_key>: <outcome_value>
  # used when no rule matches, the file is missing, or the file is
  # malformed - the engine never raises over strategy selection
```

Rules are evaluated **in file order**; the **first** rule whose `when`
conditions all match wins (no cross-rule OR, no priority field — a
deliberately minimal design, see `core.policy_engine`'s module docstring
comment for why).

### Comparators

| Comparator | Meaning |
|---|---|
| `eq` | signal value equals the given value |
| `ne` | signal value does not equal the given value |
| `in` | signal value is one of a given list |
| `not_in` | signal value is not one of a given list |
| `gte` / `lte` | signal value is >= / <= a given number |
| `gt` / `lt` | signal value is > / < a given number |

A signal absent from the profile resolves to `None`. Every comparator here
treats that as non-matching **except** `ne`/`not_in`, which — since `None`
never equals/never appears in a real expected value — vacuously pass when
the signal simply isn't present. A rule built only from negative conditions
therefore behaves as a catch-all whenever those signals are absent, not just
when they're present-but-different. This is intentional (documented and
tested in `tests/unit/libs/core/test_policy_engine.py`), not a bug — keep it
in mind when authoring a rule that relies only on `ne`/`not_in` conditions.

### Never fails the request

A missing rules file, invalid YAML syntax, or a malformed rule (an unknown
comparator, a rule missing `name`/`then`) all resolve to the caller-supplied
`fallback` rather than raising — the Adaptive Policy Pattern's explicit
"never fail the request over strategy selection" rule. Every call is logged
(`policy_engine.decision`, JSON) with the policy name, the input profile, the
matched rule (or `null` if the fallback was used), the outcome, and whether
it was a fallback — for auditability and for eval-harness-driven rule tuning
later (tune rules only via evidence, proposed as a config diff for human
review, never auto-applied — per the Adaptive Policy Pattern's rule 5).
