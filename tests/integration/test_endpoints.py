import pytest

from fastapi import APIRouter, Depends, FastAPI
from tests.unit.conftest import MockSQLModel


def create_router():
    router = APIRouter(prefix="/v1")

    from fastapi.auto_filters import create_filters

    depends_func = create_filters(MockSQLModel)

    @router.get("/test")
    async def test_endpoint(
        filters: Depends = Depends(depends_func),
    ):

        compiled_filters = [str(f.compile(compile_kwargs={"literal_binds": True})) for f in filters]

        return compiled_filters

    return router


@pytest.mark.asyncio
async def test_endpoint_without_excluded_param():
    from httpx import ASGITransport, AsyncClient

    # Create a filter model for the Composition model

    app = FastAPI()
    app.include_router(create_router(), prefix="")

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://dummy-url.com",
        headers={"authorization": "Bearer mock-token"},
    ) as ac:
        response = await ac.get(
            "v1/test",
            params={
                "field1": "test_value",
                "field2__gt": 10,
                "field2__lt": 20,
                "field3": False,
            },
        )

        assert response.status_code == 200
        data = response.json()

        assert len(data) == 4
        field2_filter_count = sum(1 for f in data if "field2" in f)
        assert field2_filter_count == 2
