import datetime as dt
import inspect
from operator import ge, gt, le, lt, ne
from typing import Any, Dict, List, Optional, Tuple, Type, Union

from fastapi import Query
from pydantic import BaseModel, Field, create_model
from sqlalchemy import BinaryExpression
from sqlmodel import SQLModel


def make_filter_model(
    model: Type[SQLModel], exclude: List[str] = None, comparators: Dict[str, Tuple[Type, ...]] = None
) -> Type[BaseModel]:
    comps = comparators or {
        "gt": (int, float, dt.date, dt.datetime),
        "gte": (int, float, dt.date, dt.datetime),
        "lt": (int, float, dt.date, dt.datetime),
        "lte": (int, float, dt.date, dt.datetime),
        "ne": (int, float, str, dt.date, dt.datetime),
        "like": (str,),
        "ilike": (str,),
        "in": (int, float, str, dt.date, dt.datetime),
    }

    exclude = exclude or []

    fields: Dict[str, Tuple[Any, Any]] = {}

    for col in model.__table__.columns:
        if col.name not in exclude:
            try:
                py_type = col.type.python_type
            except NotImplementedError:
                py_type = str

            fields[col.name] = Optional[py_type]

            for suffix, types in comps.items():
                if issubclass(py_type, types):
                    name = f"{col.name}_{suffix}"
                    if suffix == "in":
                        fields[name] = Optional[List[py_type]]
                    else:
                        fields[name] = Optional[py_type]

    FilterModel = create_model(
        f"{model.__name__}Filter",
        __base__=BaseModel,
        **{key: (typ, Field(default=None)) for key, typ in fields.items()},
    )
    return FilterModel



OP_MAP = {
    "gt": gt,
    "gte": ge,
    "lt": lt,
    "lte": le,
    "ne": ne,
}


def get_filters_from_model(
    filters: BaseModel, base_model: Union[Type[BaseModel], Type[SQLModel]]
) -> List[BinaryExpression]:
    """
    Extracts filters from a Pydantic model instance and returns a list of SQLAlchemy BinaryExpressions.
    """
    parsed_filters = []

    for param, value in filters.dict(exclude_none=True).items():
        # check for _ + any operator suffix
        if "_" in param and (
            param.rsplit("_", 1)[-1] in OP_MAP
            or param.endswith("_in")
            or param.endswith("_like")
            or param.endswith("_ilike")
        ):
            field, op = param.rsplit("_", 1)
        else:
            field, op = param, "eq"
        col = getattr(base_model, field)

        if op == "eq":
            parsed_filters.append(col == value)
        elif op in OP_MAP:
            parsed_filters.append(OP_MAP[op](col, value))
        elif op in ("like", "ilike"):
            parsed_filters.append(getattr(col, op)(value))
        elif op == "in":
            if isinstance(value, (list, tuple)):
                parsed_filters.append(col.in_(value))
            else:
                raise ValueError(f"Invalid value for 'in' operation: {value}")

    return parsed_filters


def create_filter_query_params(
    filter_model: Type[BaseModel], params_to_keep: Optional[List[str]] = None
) -> Any:
    """
    Returns a dependency function whose signature is:
        def filters(
          foo: Optional[int] = Query(None),
          foo_gt: Optional[int] = Query(None),
          bar_in: Optional[List[str]] = Query(None),
          *
        ) -> filter_model

    FastAPI will pull each of those as a query param, and then return a parsed `filter_model` instance.

    Additionally, you can specify `params_to_keep` to control which parameters are included in the OpenAPI schema,
    allowing you to hide certain parameters from the API documentation while still using them in your application.
    """
    if not params_to_keep:
        params_to_keep = []

    # Build a list of inspect.Parameters
    params: List[inspect.Parameter] = []
    for name, field in filter_model.__fields__.items():
        ann = field.outer_type_
        # Handle list types
        if name.endswith("_in") and not getattr(ann, "__origin__", None) is list:
            ann = List[ann]  # type: ignore

        param = inspect.Parameter(
            name=name,
            kind=inspect.Parameter.KEYWORD_ONLY,
            annotation=ann,
            default=Query(None, include_in_schema=name in params_to_keep),
        )
        params.append(param)

    # Create a dependency function that will be used by FastAPI
    async def _dep(**kwargs):
        # kwargs now holds raw values from query params
        return filter_model.parse_obj(kwargs)

    # Override the function's signature and name
    _dep.__signature__ = inspect.Signature(params)
    _dep.__name__ = f"dep_{filter_model.__name__}"

    return _dep
