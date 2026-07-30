from pydantic import BaseModel, Field

from app.schemas.base import StrictInputModel


class FeeRequest(StrictInputModel):
    name: str = Field(min_length=3, max_length=64)
    amount: int = Field(ge=0, le=999)


class FeeResponse(BaseModel):
    id: int
    name: str
    amount: int
