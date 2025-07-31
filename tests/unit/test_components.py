import datetime as dt

from sqlalchemy import BinaryExpression

from tests.unit.conftest import MockFilterClass, MockSQLModel


def test_make_filter_model():
    from fastapi.auto_filters import make_filter_model

    FilterModel = make_filter_model(MockSQLModel)()

    # Check if the model has the expected fields
    assert hasattr(FilterModel, "field1")
    assert hasattr(FilterModel, "field2")

    # Check if the suffix fields are present for each field
    for field_name, field in MockSQLModel.model_fields.items():

        if field.annotation == str:
            assert hasattr(FilterModel, f"{field_name}__like")
            assert hasattr(FilterModel, f"{field_name}__ilike")
            assert hasattr(FilterModel, f"{field_name}__ne")

        else:
            assert hasattr(FilterModel, f"{field_name}__in")
            assert hasattr(FilterModel, f"{field_name}__gt")
            assert hasattr(FilterModel, f"{field_name}__lt")
            assert hasattr(FilterModel, f"{field_name}__gte")
            assert hasattr(FilterModel, f"{field_name}__lte")
            assert hasattr(FilterModel, f"{field_name}__ne")

    FilterModelWithExcludedFields = make_filter_model(
        MockSQLModel, exclude_from_filters=["field1", "field2"]
    )()

    assert hasattr(FilterModelWithExcludedFields, "field1") is False
    assert hasattr(FilterModelWithExcludedFields, "field2") is False


def test_get_filters_from_model():
    from fastapi.auto_filters import get_filters_from_model

    dict_filters = {
        "field1": "test",
        "field2__gt": 10,
        "field3": True,
        "field4__gte": 5.5,
        "field5__lte": dt.date(2023, 10, 1),
    }

    expected_results = {
        "field1": "mock_sql_model.field1 = 'test'",
        "field2": "mock_sql_model.field2 > 10",
        "field3": "mock_sql_model.field3 IS true",
        "field4": "mock_sql_model.field4 >= 5.5",
        "field5": "mock_sql_model.field5 <= '2023-10-01'",
    }

    populated_filters = MockFilterClass(**dict_filters)

    filters = get_filters_from_model(populated_filters, MockSQLModel)

    # Checking each BinaryExpression
    for f in filters:
        assert isinstance(f, BinaryExpression)
        # Check if the filters match the expected values
        assert f.compile(compile_kwargs={"literal_binds": True}).string == str(
            expected_results[f.left.name]  # noqa: F821
        )
