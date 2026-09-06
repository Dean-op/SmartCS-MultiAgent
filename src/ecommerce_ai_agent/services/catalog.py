from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from ecommerce_ai_agent.repositories.product import ProductRepository
from ecommerce_ai_agent.services.data_types import ProductData


class CatalogService:
    def __init__(self, session: AsyncSession) -> None:
        self._repository = ProductRepository(session)

    async def get_product(self, product_id: UUID) -> ProductData | None:
        product = await self._repository.get_by_id(product_id)
        return ProductData.model_validate(product) if product is not None else None

    async def get_product_by_sku(self, sku: str) -> ProductData | None:
        product = await self._repository.get_by_sku(sku)
        return ProductData.model_validate(product) if product is not None else None
