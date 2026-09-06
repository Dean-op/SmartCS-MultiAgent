"""Load deterministic M2 development data into the configured PostgreSQL database."""

import asyncio

from ecommerce_ai_agent.config import Settings
from ecommerce_ai_agent.database import create_database
from ecommerce_ai_agent.seed import seed_database


async def run() -> None:
    database = create_database(Settings())
    try:
        async with database.session_factory.begin() as session:
            counts = await seed_database(session)
        print(
            "Seed data ready: "
            f"users={counts.users}, products={counts.products}, orders={counts.orders}, "
            f"shipments={counts.shipments}, refunds={counts.refunds}, reviews={counts.reviews}"
        )
    finally:
        await database.engine.dispose()


if __name__ == "__main__":
    asyncio.run(run())
