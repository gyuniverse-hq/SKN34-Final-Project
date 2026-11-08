# Graph readiness — PostgreSQL/Catalog ↔ Neo4j 비교 계약 (2026-11-09)

**Scope**: read-only legacy graph projection audit, *not* GraphRAG activation. Source: `develop` 8ef8b0fe; this work is isolated from [Draft PR #222](https://github.com/gyuniverse-hq/SKN34-Final-Project/pull/222), which changes frontend carousel, explicit selection and UI evaluation. Do not merge or modify #222 as part of this audit.

## Verified evidence and current gaps

- On 2026-11-09, a read-only query to the connected shared Supabase instance reported **7,800 products, 10,511 shades, 0 looks**, **zero populated `products.key_ingredients` arrays**, 4,801 rows in `oy_mfds_ingredient_map`, 715,482 raw option→ingredient rows, 33 records in `rec_evidence`, and 0 rows in `rec_mapping`. These are observations about the connected source, not guaranteed Neo4j counts.
- The most recent *confirmed successful* `dev-data` graph-sync log checked in this review reported **7,688 products, 0 looks** (2026-11-06 KST). Later runs attempted to wake the Render API; HTTP 503/520/524 blocked the graph-sync step. Therefore the graph is **not currently verified against 7,800 products**; it may differ by 112, but the real discrepancy requires an actual Neo4j read.
- `GraphSyncService.product_row` uses **`keyIngredients`**, which is expressly *partial*, to create `(:Product)-[:CONTAINS]->(:Ingredient)`. It does **not** export the raw option/ingredient table or standard-name evidence. Zero populated key-ingredient arrays means a fresh sync would produce **zero CONTAINS edges**, not a proof that product ingredients are absent.
- [PR #219](https://github.com/gyuniverse-hq/SKN34-Final-Project/pull/219) intentionally archived prior recommendation mappings and left new, verified v0.3 active rules empty until separately reviewed. [PR #215](https://github.com/gyuniverse-hq/SKN34-Final-Project/pull/215) contains useful identity and multi-condition code, but was **closed without merge**; it also documents that its generated product/option mapping candidate rows are unreviewed.
- The Catalog itself can change between the two read-only requests. A mismatch may therefore reflect an update racing the audit. Long-term use requires versioned, pinned snapshots.

## New functionality (isolated branch)

`backend/chatbot/app/repositories/graph_repository.py`:
- Read-only, fixed Cypher queries to enumerate the **existing** Product properties, Shade edges/attributes, key-ingredient edges, tags, and Look→Product usage. No write methods were changed.
- No LLM-generated Cypher and no schema migration.

`backend/chatbot/app/services/graph_audit_service.py`:
- Fetches the same legacy product and look projection through the **Catalog API**, rather than directly accessing PostgreSQL.
- Detects missing or unexpected IDs, mismatched prices, names, categories, texture, searchText, shades, key-ingredient names, tags, and look relationships. Duplicate IDs and an empty Catalog cause failure. Samples are capped at 10 IDs.
- Reports `fullIngredientEvidenceVerified=false` and `recommendationEvidenceVerified=false` regardless of parity. Even `status=PASS` means **legacy projection equality only**.

`backend/chatbot/app/jobs/audit_graph.py`:
- Run in the existing chatbot environment: `uv run python -m app.jobs.audit_graph`.
- Uses `CATALOG_API_URL` and `NEO4J_URI` plus Neo4j credentials already configured for the existing sync job.
- Exit `0`: projection match; `2`: drift; `3`: API or Neo4j read failure. Prints JSON; no writes, re-seeding, or graph replacement.
- For safety, run manually in a configured environment before considering CI/scheduled monitoring. **Do not put credentials in issue comments or logs.**
- Offline unit tests: `cd backend/chatbot && uv run pytest tests/test_graph_audit.py -q`.

## Blocks before GraphRAG activation

1. **Ops**: investigate Render API unavailability and prevent `dev-data` from blocking API deployments. Do not silence failures with a `continue-on-error` that reports sync success.
2. **Projection parity**: run the new audit against the actual dev AuraDB and API. Review count and exact ID differences. This audit cannot report the live result until the job is executed with Neo4j read credentials.
3. **Owner contract**: design an authenticated, versioned, paginated Graph Export API for **reviewed option identities** and **ingredient evidence**; do not treat `keyIngredients` as full or assume raw product/option ownership. Retain original text, canonical ID, provenance, completeness and approval.
4. **Neo4j schema**: separate Product, Option, Shade, canonical Ingredient, and the Rule/Concern/Evidence graph. Ensure legacy full replacement doesn't accidentally destroy expanded evidence edges. Agree on node/edge budget and graph versioning.
5. **Ingredient consultation**: cherry-pick/rework PR #215 only after rebasing its identity contracts onto current `develop` and resolving the missing reviewed runtime mapping. Missing evidence must remain `UNKNOWN`. Don't activate with synthetic fixtures.
6. **LLM Tool contract**: implement fixed, read-only graph queries returning IDs and provenance to the current Supervisor/Beauty path; revalidate all product/option/ingredient facts via Catalog before answering. Never let graph ranking override user constraints.
7. **Evidence policy**: only publish approved v0.3 mapping rules and their limitations; don't migrate legacy 47,599 match rows as if they were active verified facts.
8. **Validation**: DB identity and edge parity; independent ingredient inclusion/exclusion tests; historical-candidate preservation; regression on the 359-case suite; Graph vs Catalog-only latency and accuracy. Keep PR #222 UI tests isolated.

## Decision

**This PR is a prerequisite and observability tool, not an implementation of Neo4j-backed product recommendation.** Do not enable a new Graph Knowledge Tool or promise ingredient efficacy on the basis of a successful legacy projection audit. No Supabase/AuraDB changes, CI schema migrations, PR merges, paid LLM calls, or app UI changes belong to this work unit.
