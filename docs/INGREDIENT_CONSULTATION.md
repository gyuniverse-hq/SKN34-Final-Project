# Ingredient consultation contract and acceptance scenarios

The API owns product/option evidence and canonical ingredient identity. The chatbot
uses the API HTTP contract, checks the proof again, and keeps unresolved products
explicitly unknown. No database migration or shared-data update is part of this change.

## Evidence contract

- Product/shade → raw option mapping still requires a reproduced generator run,
  matching catalog and source versions, reviewed evidence, and original provenance.
  `oy_mfds_ingredient_map` only establishes ingredient identity; it cannot establish
  product/option ownership or full-list coverage.
- Raw ingredient `name` and `sequence` remain unchanged. Optional `identity` carries
  the current MFDS ID, official name, dictionary source hash, matching method and
  rule version (or manual reviewer and timestamp). Missing/invalid/inactive links
  stay unresolved. No fuzzy matching or model-generated identity is used.
  Automatic links are rechecked against the current official name/synonym and
  conservative trailing-amount rule. Manual links lack a reviewed dictionary hash
  in the current DB schema and remain unresolved until that versioned review exists.
- Queries resolve against current official Korean/English names, official comma-
  separated synonyms, or confirmed Olive Young aliases. Multiple distinct candidate
  IDs remain unresolved. Each condition returns its optional `queryIdentity`.
- Literal reviewed presence remains supported. Canonical presence additionally
  requires the same ID and dictionary source hash. Absence requires a reviewed,
  complete, normalized, sequential and unique list, identities for **every** entry,
  a resolved query, and no contradictory identity version. Missing evidence never
  becomes a claim of absence or general fragrance-free status.
- A catalog product with no shades can use a reviewed artifact record with
  `shadeId: null` and a verified option. Products with shades still require selection;
  no shade or option is invented or silently selected.
- `ingredientConditions` in a planner response can represent up to six simultaneous
  constraints. Follow-up constraints merge by normalized name; only explicit
  `clearFilters: ["ingredientConditions"]` clears them. The legacy single condition
  remains compatible. Detail questions can also evaluate multiple constraints.

## Scenario design

Use alternate product IDs, ingredient names, list order and natural language in
independent evaluation. Mock plans verify execution; they do not prove LLM extraction.

| Scenario | Example intent | Required observation |
| --- | --- | --- |
| Product → ingredient | Does this option contain X? / Is X listed here? | Same result for reviewed original, official English and Korean identities; original text preserved |
| Ingredient → products | Show creams containing X, excluding Y | All requested constraints and price/category bounds are retained; unknown candidates remain marked |
| Product/option change | Check the second product / switch to another shade | Re-fetch selected evidence; no stale option verdict |
| No shade | Check ingredients of this colorless serum | Null shade accepted only when catalog has no shades and artifact provides reviewed option |
| Compound follow-up | Add Z / now exclude X / remove ingredient constraints | Merge, replace same named constraint, explicit clear, six-condition limit |
| Missing mapping | Raw row exists but option artifact is candidate | UNKNOWN; do not promote candidate or expose unreviewed rows as facts |
| Partial identity/list | One unresolved ingredient, missing sequence or partial coverage | Presence may be established; absence remains UNKNOWN |
| Identity conflict | Ambiguous alias, retired standard, mismatched source hash | UNKNOWN or rejected malformed contract; no chemical-family inference |
| Errors | API 503, timeout, malformed JSON | ERROR distinct from no products or absent ingredient |
| Sessions | Expired/foreign session, price follow-up, retry | Existing ownership, revalidation, idempotency and partial-result behavior preserved |

## Runtime prerequisites and validation boundaries

Set `INGREDIENT_MAPPING_PATH` to an absolute, reviewed artifact path. An empty or
candidate-only artifact does not enable verified product facts. See
`docs/DEPLOYMENT.md` and `infra/compose/compose.ingredients.yaml` for the existing
read-only mount contract. The canonical links require the existing current MFDS
dictionary and `oy_mfds_ingredient_map`; this change only SELECTs these tables.

Record mock SQL/LLM, loopback HTTP, real PostgreSQL, real Redis, paid LLM and device
checks separately. A passing synthetic verdict is not a reviewed operating product.
The session-specific readiness evidence and unresolved data approvals are in the
implementation handoff/PR; the personal harness stays outside team Git.
