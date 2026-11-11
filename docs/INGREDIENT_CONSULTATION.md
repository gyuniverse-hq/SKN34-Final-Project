# Ingredient consultation contract and acceptance scenarios

The API owns product/option evidence and canonical ingredient identity. The chatbot
uses the API HTTP contract, checks the proof again, and keeps unresolved products
explicitly unknown. No database migration or shared-data update is part of this change.

## Evidence contract

- The current MFDS table mixes `^` and legacy comma-separated synonyms.
  Both read-only API and `scripts/data/ingredients/match_oy_mfds.py` now
  parse these formats consistently, without splitting chemical locants such
  as `1,2-헥산디올` or `N,N-`. This is a conservative compatibility rule,
  not blanket authority to treat arbitrary commas as separators.
  The importer produces `mfds-alias-review.csv` for every non-empty
  `synonym_raw` value, including the previously omitted single aliases. Each
  row retains MFDS ID, original source string, source hash, competing IDs and
  `source_backed` / `review_required` / `ambiguous` status.
  - Exact official Korean/English names and single unsplit dictionary synonyms
    remain source-backed. Split aliases require an approved, version-bound row.
  - For new `official_synonym` / `amount_suffix_synonym` matches, pass a separate
    `--approvals-file` CSV with `mfds_ingredient_id,candidate_alias,source_hash,reviewed_by,reviewed_at`.
    Stale or ambiguous approvals fail; unapproved new automatic matches cause
    `--apply` to abort before DB mutation. `amount_suffix_exact` needs no alias
    approval when stripping one supported trailing numeric concentration
    (`ppm`, `ppb`, `%`, or `IU`) yields a unique official Korean or English name.
  - Configure the same read-only CSV for API using the absolute environment path
    `INGREDIENT_ALIAS_APPROVALS_PATH`. Without a file, split aliases stay unresolved
    while source-backed names remain available. A configured missing, unreadable
    or malformed CSV returns HTTP 503 with `ingredient_alias_approvals_invalid`
    from the ingredient endpoint. The chatbot reports `source_unavailable`
    (`ERROR`); ordinary catalog endpoints are unaffected. Restart the API after
    updating the mounted CSV.
  - A successful apply stores the reviewer, review timestamp and source hash
    (`review_note`) in the existing `oy_mfds_ingredient_map` columns, and exports
    a timestamped `applied-mfds-approvals-*.csv` receipt. Retain the original signed-off CSV
    and receipt in versioned, access-controlled storage for audit. Neither a
    preview CSV nor code tests constitute human review.
  CI exercises the parser, approval guard and review queue on synthetic inputs.
  This PR does not write to shared DB mappings or change review states.
- A read-only audit of the existing shared DB found 528 `official_synonym`
  links: 527 pass the mixed-delimiter check, while OY ID 2974 (`2-헥산디올`)
  linked to MFDS ID 4840 (`1,2-헥산디올`) remains invalid. Preserve that
  mapping as unresolved until reviewed. Rerun the audit for fresh DB snapshots.

- Product/shade to raw option mapping accepts generator replay or direct review.
  Direct review uses `mappingStatus: directly_reviewed` and `mappingMethod: direct_review`.
  Record `reviewedBy`, timezone-aware `reviewedAt`, and `reviewRef` pointing to
  the recorded option and disclosure comparison. Set `reviewStatus: verified`
  only after checking that the disclosure covers the selected option. Both paths
  require matching catalog and source versions and active option ownership.
  On the direct review path, an unknown source timezone is reported as
  `source_timezone_unknown`. The original value stays in `collectedAtRaw`,
  and `reviewedAt` records the separate review time.
  `oy_mfds_ingredient_map` only establishes ingredient identity; it cannot establish
  product/option ownership or full-list coverage.
- Raw ingredient `name` and `sequence` remain unchanged. Optional `identity` carries
  the current MFDS ID, official name, dictionary source hash, matching method and
  rule version (or manual reviewer and timestamp). Missing/invalid/inactive links
  stay unresolved. No fuzzy matching or model-generated identity is used.
  Automatic links are rechecked against the current official name/synonym and
  conservative trailing-amount rule. Manual links lack a reviewed dictionary hash
  in the current DB schema and remain unresolved. A future manual-link contract
  must bind the reviewed Olive Young spelling and target MFDS ID to the reviewed
  dictionary hash, reviewer, and review date, and reject stale or conflicting links.
- Queries resolve against current official Korean/English names, validated mixed-
  delimiter official synonyms, or confirmed Olive Young aliases. An explicit
  Korean or English official-name query uses its sole official owner, even if
  another ID lists the name as an alias. Duplicate official owners stay
  unresolved. Product entries, automatic matching and alias approvals require
  one owner across Korean names, English names, and all aliases, including
  unapproved split aliases. Each condition returns its optional `queryIdentity`.
- Literal reviewed presence remains supported. Canonical presence additionally
  requires the same ID and dictionary source hash. Absence requires a reviewed,
  complete, normalized, sequential and unique list, identities for **every** entry,
  a resolved query, and no contradictory identity version. Missing evidence never
  becomes a claim of absence or general fragrance-free status.
- When filtering ingredients and fragrance together, a limited scan continues past
  unverified candidates to find verified `MATCH` results before taking up to
  six display slots; unknown results are retained explicitly if slots remain.
  The same request-count and deadline budgets still apply.
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
| Ingredient + fragrance | Find X-containing fragrance-free products | Exclude verified X-mismatches, retain X-unknown separately; fragrance stays unverified |
| Fragrance follow-up | Add fragrance-free to a previous X-ingredient search | Keep and recheck inherited X condition without fabricating a fragrance match |
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
