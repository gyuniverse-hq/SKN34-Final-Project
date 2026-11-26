from typing import get_args

from pydantic import Field

from app.schemas.chat import ArChroma, ArColorFamily, ArLightness, ArLipType, ArModel, ArZone


class ArCatalogTarget(ArModel):
    name: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
        description=(
            "Complete shade name or shade number as spoken, without the separate brand, "
            "product line or grammatical particles. Omit when the user delegates shade selection."
        ),
    )
    brand: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
        description="Brand explicitly named in the request. Copy it as spoken.",
    )
    product: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
        description="Spoken catalog reference for a product line named in the request.",
    )
    zone: ArZone | None = Field(
        default=None, description="Makeup zone requested by the user, if specified."
    )


def ar_control_tool(choices: list[str], *, resolve_catalog_target: bool = False) -> dict:
    tool = {
        "name": "ar_control",
        "description": "Perform one operation offered by the current AR screen.",
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "choice": {
                    "type": "string",
                    "enum": choices
                    if resolve_catalog_target
                    else [choice for choice in choices if choice != "apply_shade/product_pick"],
                },
                "lipType": {
                    "type": "string",
                    "enum": get_args(ArLipType),
                    "description": "Explicit lip product type for catalog selection.",
                },
                "family": {
                    "type": "string",
                    "enum": get_args(ArColorFamily),
                    "description": "Optional hue family for by_color or product_pick.",
                },
                "lightness": {
                    "type": "string",
                    "enum": get_args(ArLightness),
                    "description": ("Optional perceptual lightness of the shade for by_color."),
                },
                "chroma": {
                    "type": "string",
                    "enum": get_args(ArChroma),
                    "description": "Optional color saturation of the shade for by_color.",
                },
                "lookupDetail": {
                    "type": "string",
                    "enum": ["count", "list"],
                    "description": "For find_shades only. Omit for availability. Use count "
                    "only if the user asks how many; list only if they ask for options.",
                },
                "name": {"type": "string", "description": "Catalog name from user input"},
                "value": {"type": "number", "minimum": 0, "maximum": 1.7},
                "steps": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 100,
                    "description": "For step_shade only. Count chips from the selected chip "
                    "in the current palette's displayed order. Defaults to one adjacent chip.",
                },
                "ordinal": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 2**53 - 1,
                    "description": "One-based wear order within the requested zone, or all zones "
                    "for reapply_try_on/all. Only for reapply_try_on.",
                },
                "productId": {
                    "type": "string",
                    "description": "Exact product ID from screen",
                },
                "shadeId": {"type": "string", "description": "Exact shade ID from screen"},
            },
            "required": ["choice"],
        },
    }
    if resolve_catalog_target:
        properties = tool["parameters"]["properties"]
        del properties["productId"], properties["shadeId"]
        properties["catalogTarget"] = {
            **ArCatalogTarget.model_json_schema(),
            "description": (
                "Required for product_shade and product_pick. Use name for any specifically "
                "requested shade, even when unverified. Use product alone for product_pick. "
                "Omit for recommendations without a specific catalog identity."
            ),
        }
    return tool
