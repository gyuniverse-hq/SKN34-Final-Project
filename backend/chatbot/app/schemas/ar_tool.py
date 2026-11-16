from typing import get_args

from app.schemas.chat import ArChroma, ArColorFamily, ArLightness, ArLipType


def ar_control_tool(choices: list[str]) -> dict:
    return {
        "name": "ar_control",
        "description": "Perform one operation offered by the current AR screen.",
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "choice": {"type": "string", "enum": choices},
                "lipType": {
                    "type": "string",
                    "enum": get_args(ArLipType),
                    "description": "Explicit lip product type for catalog selection.",
                },
                "family": {
                    "type": "string",
                    "enum": get_args(ArColorFamily),
                    "description": "Optional hue family for by_color. Omit if unspecified.",
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
                "steps": {"type": "integer", "minimum": 1, "maximum": 100},
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
