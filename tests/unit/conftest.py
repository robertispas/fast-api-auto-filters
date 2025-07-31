import datetime as dt

from pydantic import BaseModel
from sqlmodel import Field, SQLModel


class MockSQLModel(SQLModel, table=True):
    __tablename__ = "mock_sql_model"
    __table_args__ = {"extend_existing": True}

    field1: str = Field(primary_key=True)
    field2: int
    field3: bool
    field4: float
    field5: dt.date


class MockFilterClass(BaseModel):
    field1__eq: str = Field(default=None)
    field2__gt: int = Field(default=None)
    field3: bool = Field(default=None)
    field4__gte: float = Field(default=None)
    field5__lte: dt.date = Field(default=None)
