-- Checks a restored local DB against the numbers in README_TEAM_SETUP.md.
-- setup_local_db.cmd runs this. By hand, from the repository root:
--   docker compose -f infra/compose/compose.yaml exec -T postgres
--     psql -P pager=off -v ON_ERROR_STOP=1 -U vishue -d vishue_db < scripts/data/verify_local_db.sql
SELECT
    item,
    actual,
    expected,
    CASE WHEN actual = expected THEN 'OK' ELSE 'MISMATCH' END AS result
FROM (
    SELECT 'products' AS item,
           (SELECT count(*) FROM products) AS actual,
           7688 AS expected
    UNION ALL
    SELECT 'shades', (SELECT count(*) FROM shades), 10160
    UNION ALL
    SELECT 'aihub_skin_concern', (SELECT count(*) FROM aihub_skin_concern), 13
    UNION ALL
    SELECT 'aihub_skin_type', (SELECT count(*) FROM aihub_skin_type), 4
    UNION ALL
    SELECT 'public tables',
           (SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public'),
           57
) t;
