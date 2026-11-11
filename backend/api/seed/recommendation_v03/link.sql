-- Same trim characters as the release's Python str.strip(), including Unicode spaces.
WITH whitespace AS (
    SELECT U&'\0009\000A\000B\000C\000D\001C\001D\001E\001F\0020\0085\00A0\1680' ||
           U&'\2000\2001\2002\2003\2004\2005\2006\2007\2008\2009\200A\2028\2029\202F\205F\3000' AS chars
), policy AS (SELECT CAST(:policy AS jsonb) AS doc),
names AS (
    SELECT d.ingredient_code, normalize(btrim(d.name_ko, (SELECT chars FROM whitespace))) AS name, 'exact_name' AS method,
           coalesce((r->>'exact_name_auto_link')::boolean, false) AS allowed
    FROM rec_ingredient_dictionary d
    LEFT JOIN (SELECT jsonb_array_elements(doc->'rules') AS r FROM policy) rules
      ON r->>'ingredient_code' = d.ingredient_code
), candidates AS (
    SELECT * FROM names
    UNION ALL
    SELECT n.ingredient_code, normalize(btrim(a->>'source_name', (SELECT chars FROM whitespace))), 'verified_alias', n.allowed
    FROM policy CROSS JOIN LATERAL jsonb_array_elements(doc->'verified_aliases') a
    JOIN names n ON n.ingredient_code = a->>'ingredient_code'
    WHERE length(a->>'basis') > 0 AND length(a->>'limit') > 0
), owners AS (
    SELECT name, count(DISTINCT ingredient_code) AS n FROM candidates GROUP BY name
), raw_names AS (
    SELECT normalize(btrim(ingredient_name, (SELECT chars FROM whitespace))) AS name, count(*) AS n, min(ingredient_id) AS id
    FROM raw_oy_ingredient GROUP BY 1
), checked AS (
    SELECT c.*, r.id, bool_and(c.allowed AND owners.n=1 AND coalesce(r.n,0)<=1)
        OVER (PARTITION BY c.ingredient_code) AS unambiguous
    FROM candidates c JOIN owners USING(name) LEFT JOIN raw_names r USING(name)
), desired AS MATERIALIZED (
    SELECT ingredient_code, id, method FROM checked WHERE unambiguous AND id IS NOT NULL
), removed AS (
    DELETE FROM rec_ingredient_link l WHERE l.link_method IN ('exact_name','verified_alias')
    AND NOT EXISTS (SELECT 1 FROM desired d WHERE d.ingredient_code=l.ingredient_code
                    AND d.id=l.oy_ingredient_id)
)
INSERT INTO rec_ingredient_link (ingredient_code,oy_ingredient_id,link_method)
SELECT ingredient_code,id,method FROM desired
ON CONFLICT (ingredient_code,oy_ingredient_id) DO UPDATE
SET link_method=excluded.link_method, linked_at=now()
WHERE rec_ingredient_link.link_method IN ('exact_name','verified_alias')
  AND rec_ingredient_link.link_method <> excluded.link_method
