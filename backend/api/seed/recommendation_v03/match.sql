WITH matches AS MATERIALIZED (
SELECT mi.mapping_id, oi.option_id, now()
FROM rec_mapping_ingredient mi
JOIN rec_ingredient_link l ON l.ingredient_code = mi.ingredient_code
JOIN raw_oy_option_ingredient oi ON oi.ingredient_id = l.oy_ingredient_id
GROUP BY mi.mapping_id, oi.option_id
HAVING count(DISTINCT mi.ingredient_code) = (
    SELECT count(DISTINCT x.ingredient_code) FROM rec_mapping_ingredient x
    WHERE x.mapping_id = mi.mapping_id
)
), deleted AS (
    DELETE FROM rec_concern_match old
    WHERE NOT EXISTS (SELECT 1 FROM matches m
                      WHERE m.mapping_id = old.mapping_id AND m.option_id = old.option_id)
    RETURNING 1
), inserted AS (
    INSERT INTO rec_concern_match (mapping_id, option_id, computed_at)
    SELECT mapping_id, option_id, now FROM matches
    ON CONFLICT (mapping_id, option_id) DO NOTHING
    RETURNING 1
)
SELECT (SELECT count(*) FROM deleted) + (SELECT count(*) FROM inserted)
