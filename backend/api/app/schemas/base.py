from typing import Any

from pydantic import BaseModel, ConfigDict, SerializerFunctionWrapHandler, model_serializer
from pydantic.alias_generators import to_camel


class ApiModel(BaseModel):
    """JSON uses camelCase like the app's `types/index.ts`; Python code uses snake_case."""

    model_config = ConfigDict(
        alias_generator=to_camel, populate_by_name=True, serialize_by_alias=True
    )


class OmitNoneModel(ApiModel):
    """For TS optional fields (`shadeId?: string`): omit the key instead of sending null."""

    @model_serializer(mode="wrap")
    def _omit_none(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        return {k: v for k, v in handler(self).items() if v is not None}
