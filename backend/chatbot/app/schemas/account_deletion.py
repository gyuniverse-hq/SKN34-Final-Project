from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class InternalAccountDeletion(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    job_id: UUID = Field(alias="jobId")
    owner_id: str = Field(alias="ownerId", min_length=1, max_length=64)
