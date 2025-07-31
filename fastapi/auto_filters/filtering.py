"""The main module of the package."""

import datetime as dt
import inspect
from operator import ge, gt, le, lt, ne
from typing import Any, Dict, List, Optional, Tuple, Type, Union, get_args, get_origin

from pydantic import BaseModel, Field, create_model
from sqlalchemy import BinaryExpression, Boolean
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.orm.exc import UnmappedClassError
from sqlmodel import SQLModel

from fastapi import Query

ModelType = Type[SQLModel]


def make_filter_model(
    base_model: ModelType,
    exclude_from_filters: list[str] = None,
) -> Type[BaseModel]:
    """Create a filter model from a SQLModel model.

    For each column in the base model, generate optional query-param fields for
    eq, gt, gte, lt, lte, ne, like, ilike, and in.

    Args:
        base_model: The Pydantic or SQLModel class to derive filters from.
        exclude_from_filters: Optional list of column names to skip.

    Returns:
        A new Pydantic BaseModel subclass representing all filter fields.
    """
    comps = {
        "gt": (int, float, dt.date, dt.datetime),
        "gte": (int, float, dt.date, dt.datetime),
        "lt": (int, float, dt.date, dt.datetime),
        "lte": (int, float, dt.date, dt.datetime),
        "ne": (bool, int, float, str, dt.date, dt.datetime),
        "like": str,
        "ilike": str,
        "in": (int, float, str, dt.date, dt.datetime),
    }

    exclude = exclude_from_filters or []

    fields: Dict[str, Tuple[Any, Any]] = {}

    for col_name, col in base_model.model_fields.items():
        if col_name not in exclude:
            try:
                py_type = col.annotation
            except NotImplementedError:
                py_type = str

            fields[col_name] = Optional[py_type]

            for suffix, types in comps.items():
                if issubclass(py_type, types):
                    name = f"{col_name}__{suffix}"
                    if suffix == "in":
                        fields[name] = Optional[List[py_type]]
                    else:
                        fields[name] = Optional[py_type]

    FilterModel = create_model(
        f"{base_model.__name__}Filter",
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


def get_filters_from_model(filters: BaseModel, base_model: ModelType) -> list[BinaryExpression]:
    """Extract SQLAlchemy filter expressions from a filter model instance.

    Parse each field on `filters`, map its suffix (eq, gt, lt, etc.) to
    the matching SQLAlchemy operation, and return the combined list.

    Args:
        filters: An instantiated filter model containing only non-None values.
        base_model: The original model class used to create the filter model.

    Returns:
        A list of SQLAlchemy BinaryExpression objects ready to be applied.

    Raises:
        TypeError: If `base_model` is not a SQLAlchemy-mapped class.
        ValueError: If an unsupported operation is encountered.
    """
    try:
        sa_inspect(base_model)
    except UnmappedClassError:
        raise TypeError(f"{base_model!r} is not a SQLAlchemy‐mapped class")

    parsed_filters = []

    for param, value in filters.model_dump(exclude_none=True).items():
        if "__" in param and (
            param.rsplit("__", 1)[-1] in OP_MAP
            or param.endswith("__in")
            or param.endswith("__like")
            or param.endswith("__ilike")
        ):
            field, op = param.rsplit("__", 1)
        else:
            field, op = param, "eq"
        col = getattr(base_model, field)

        if isinstance(col.type, Boolean):
            if op == "eq":
                op = "is"
            elif op == "ne":
                op = "is_not"

        if op == "eq":
            parsed_filters.append(col == value)
        elif op == "is":
            parsed_filters.append(col.is_(value))
        elif op == "is_not":
            parsed_filters.append(col.is_not(value))
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


def create_filters(
    base_model: ModelType,
    keep_in_schema_params: Optional[List[str]] = None,
    exclude_from_filters: Optional[List[str]] = None,
) -> callable:
    """Create a FastAPI dependency that produces SQLAlchemy filters from query params.

    Build a pydantic filter model, generate Query() parameters for each field,
    and return a dependency callable that yields a list of BinaryExpressions.

    Args:
        base_model: The model class to generate filter parameters from.
        keep_in_schema_params: Optional list of filter names to include in OpenAPI.
        exclude_from_filters: Optional list of filter names to omit entirely.

    Returns:
        A FastAPI dependency function which, when called, returns filter expressions.
    """
    if not keep_in_schema_params:
        keep_in_schema_params = []

    filter_model = make_filter_model(base_model, exclude_from_filters=exclude_from_filters)

    # Build a list of inspect.Parameters
    params: list[inspect.Parameter] = []
    for name, field in filter_model.model_fields.items():
        # Grab the “real” type: prefer outer_type_ (ModelField), fallback to annotation (FieldInfo)
        if hasattr(field, "outer_type_"):
            ann = field.outer_type_
        else:
            ann = field.annotation

        # If it’s Optional[X], unwrap to X
        origin = get_origin(ann)
        args = get_args(ann)
        if origin is Union and type(None) in args:
            ann = next(a for a in args if a is not type(None))

        param = inspect.Parameter(
            name=name,
            kind=inspect.Parameter.KEYWORD_ONLY,
            annotation=ann,
            default=Query(None, include_in_schema=name in keep_in_schema_params),
        )
        params.append(param)

    # Create a dependency function that will be used by FastAPI
    async def _dep(**kwargs) -> list[BinaryExpression]:
        # kwargs now holds raw values from query params
        return get_filters_from_model(filter_model.model_validate(kwargs), base_model=base_model)

    # Override the function's signature and name
    _dep.__signature__ = inspect.Signature(params)
    _dep.__name__ = "filters"

    return _dep
