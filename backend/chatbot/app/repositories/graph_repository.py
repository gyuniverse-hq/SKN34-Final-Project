from typing import Any

from neo4j import AsyncDriver, AsyncManagedTransaction, RoutingControl

from app.schemas.chat import GraphProduct

# Graph model (filled one way from the api service's catalog):
#   (:Product)-[:HAS_SHADE]->(:Shade)   (:Product)-[:CONTAINS]->(:Ingredient)
#   (:Product|:Look)-[:TAGGED]->(:Tag)  (:Look)-[:USES {step, shadeId}]->(:Product)

SCHEMA = [
    "CREATE CONSTRAINT product_id IF NOT EXISTS FOR (n:Product) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT look_id IF NOT EXISTS FOR (n:Look) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT ingredient_name IF NOT EXISTS FOR (n:Ingredient) REQUIRE n.name IS UNIQUE",
    "CREATE CONSTRAINT tag_name IF NOT EXISTS FOR (n:Tag) REQUIRE n.name IS UNIQUE",
]

FIND_PRODUCTS = """
MATCH (p:Product)
WITH p, size([t IN $terms WHERE p.searchText CONTAINS t]) AS score
WHERE score > 0
OPTIONAL MATCH (p)-[:CONTAINS]->(i:Ingredient)
OPTIONAL MATCH (p)-[:TAGGED]->(t:Tag)
OPTIONAL MATCH (l:Look)-[:USES]->(p)
WITH p, score, collect(DISTINCT i.name) AS ingredients, collect(DISTINCT t.name) AS tags,
     collect(DISTINCT l.title) AS looks
RETURN p.id AS id, p.brand AS brand, p.name AS name, p.category AS category,
       p.texture AS texture, p.priceKRW AS priceKRW, ingredients, tags, looks
ORDER BY score DESC, p.id
LIMIT $limit
"""

CLEAR = "MATCH (n) WHERE n:Product OR n:Shade OR n:Ingredient OR n:Tag OR n:Look DETACH DELETE n"

CREATE_PRODUCTS = """
UNWIND $products AS p
CREATE (n:Product {id: p.id, brand: p.brand, name: p.name, nameKo: p.nameKo,
                   category: p.category, texture: p.texture, priceKRW: p.priceKRW,
                   searchText: p.searchText})
FOREACH (s IN p.shades | CREATE (n)-[:HAS_SHADE]->(:Shade {id: s.id, name: s.name, hex: s.hex}))
FOREACH (name IN p.ingredients | MERGE (i:Ingredient {name: name}) CREATE (n)-[:CONTAINS]->(i))
FOREACH (name IN p.tags | MERGE (t:Tag {name: name}) CREATE (n)-[:TAGGED]->(t))
"""

CREATE_LOOKS = """
UNWIND $looks AS l
CREATE (k:Look {id: l.id, title: l.title})
FOREACH (name IN l.tags | MERGE (t:Tag {name: name}) CREATE (k)-[:TAGGED]->(t))
WITH k, l
UNWIND l.items AS item
MATCH (p:Product {id: item.productId})
CREATE (k)-[:USES {step: item.step, shadeId: item.shadeId}]->(p)
"""


class GraphRepository:
    """The only module that talks to Neo4j. Used by the chat and graph sync services."""

    def __init__(self, driver: AsyncDriver) -> None:
        self._driver = driver

    async def find_products(self, terms: list[str], limit: int = 6) -> list[GraphProduct]:
        if not terms:
            return []
        result = await self._driver.execute_query(
            FIND_PRODUCTS, terms=terms, limit=limit, routing_=RoutingControl.READ
        )
        return [GraphProduct.model_validate(r.data()) for r in result.records]

    async def ensure_schema(self) -> None:
        for statement in SCHEMA:
            await self._driver.execute_query(statement)

    async def replace_catalog(
        self, products: list[dict[str, Any]], looks: list[dict[str, Any]]
    ) -> None:
        """One write transaction, so readers see either the old graph or the new one."""

        async def work(tx: AsyncManagedTransaction) -> None:
            await (await tx.run(CLEAR)).consume()
            await (await tx.run(CREATE_PRODUCTS, products=products)).consume()
            await (await tx.run(CREATE_LOOKS, looks=looks)).consume()

        async with self._driver.session() as session:
            await session.execute_write(work)
