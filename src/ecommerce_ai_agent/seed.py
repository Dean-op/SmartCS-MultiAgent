from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from uuid import UUID, uuid5

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from ecommerce_ai_agent.auth import hash_password
from ecommerce_ai_agent.models import (
    HumanReview,
    KnowledgeDocument,
    Order,
    OrderItem,
    Product,
    Refund,
    Shipment,
    User,
)
from ecommerce_ai_agent.models.enums import (
    OrderStatus,
    PaymentStatus,
    RefundStatus,
    ReviewPriority,
    ReviewStatus,
    ShipmentStatus,
    UserRole,
)

SEED_NAMESPACE = UUID("7cff7d68-238c-4a0d-b4ce-4e82c9fd0555")
SEED_EPOCH = datetime(2026, 8, 1, 8, 0, tzinfo=UTC)

USER_DEFINITIONS = (
    ("alice@example.com", UserRole.CUSTOMER),
    ("bob@example.com", UserRole.CUSTOMER),
    ("carol@example.com", UserRole.CUSTOMER),
    ("dave@example.com", UserRole.CUSTOMER),
    ("erin@example.com", UserRole.CUSTOMER),
    ("admin@example.com", UserRole.ADMIN),
)

PRODUCT_DEFINITIONS = (
    ("ELEC-HUB-001", "USB-C 多功能扩展坞", "299.00"),
    ("ELEC-MOUSE-002", "静音无线鼠标", "129.00"),
    ("ELEC-KEYBOARD-003", "机械键盘", "499.00"),
    ("ELEC-HEADSET-004", "降噪蓝牙耳机", "899.00"),
    ("OFFICE-STAND-005", "铝合金笔记本支架", "189.00"),
    ("ELEC-WEBCAM-006", "高清会议摄像头", "399.00"),
    ("HOME-LAMP-007", "智能护眼台灯", "159.00"),
    ("HOME-MUG-008", "不锈钢保温杯", "89.00"),
    ("OFFICE-CUSHION-009", "人体工学坐垫", "219.00"),
    ("ELEC-SSD-010", "1TB 移动固态硬盘", "699.00"),
    ("ELEC-CHARGER-011", "100W 氮化镓充电器", "249.00"),
    ("ELEC-CABLE-012", "双头 USB-C 数据线", "59.00"),
)


@dataclass(frozen=True, slots=True)
class SeedCounts:
    users: int
    products: int
    orders: int
    shipments: int
    refunds: int
    reviews: int
    knowledge_documents: int


def seed_id(key: str) -> UUID:
    return uuid5(SEED_NAMESPACE, key)


def build_knowledge_rows() -> list[dict]:
    knowledge_directory = Path(__file__).resolve().parents[2] / "knowledge"
    rows = []
    for path in sorted(knowledge_directory.glob("*.md")):
        content = path.read_text(encoding="utf-8").strip()
        title = content.splitlines()[0].lstrip("# ").strip() or path.stem
        rows.append(
            {
                "id": seed_id(f"knowledge:{path.name}"),
                "title": title,
                "source": path.name,
                "content": content,
                "content_hash": sha256(content.encode()).hexdigest(),
                "indexed_hash": None,
                "indexed_at": None,
                "created_at": SEED_EPOCH,
                "updated_at": SEED_EPOCH,
            }
        )
    return rows


def order_state(index: int) -> tuple[OrderStatus, PaymentStatus]:
    if index <= 4:
        return OrderStatus.PENDING_PAYMENT, PaymentStatus.UNPAID
    if index <= 9:
        return OrderStatus.PROCESSING, PaymentStatus.PAID
    if index <= 14:
        return OrderStatus.SHIPPED, PaymentStatus.PAID
    if index <= 21:
        if index == 18:
            return OrderStatus.COMPLETED, PaymentStatus.PARTIALLY_REFUNDED
        if index == 20:
            return OrderStatus.COMPLETED, PaymentStatus.REFUNDED
        return OrderStatus.COMPLETED, PaymentStatus.PAID
    return OrderStatus.CANCELLED, PaymentStatus.UNPAID


def build_seed_rows() -> dict[str, list[dict]]:
    users = [
        {
            "id": seed_id(f"user:{email}"),
            "email": email,
            "password_hash": None,
            "role": role,
            "is_active": True,
            "created_at": SEED_EPOCH,
            "updated_at": SEED_EPOCH,
        }
        for email, role in USER_DEFINITIONS
    ]
    products = [
        {
            "id": seed_id(f"product:{sku}"),
            "sku": sku,
            "name": name,
            "description": f"M2 开发测试商品：{name}",
            "unit_price": Decimal(price),
            "is_active": True,
            "created_at": SEED_EPOCH,
            "updated_at": SEED_EPOCH,
        }
        for sku, name, price in PRODUCT_DEFINITIONS
    ]

    orders: list[dict] = []
    order_items: list[dict] = []
    totals: dict[int, Decimal] = {}
    for index in range(1, 25):
        created_at = SEED_EPOCH + timedelta(days=index)
        status, payment_status = order_state(index)
        product_indexes = [(index - 1) % len(products)]
        if index % 2 == 0:
            product_indexes.append(index % len(products))
        if index % 3 == 0:
            product_indexes.append((index + 3) % len(products))

        total = Decimal("0.00")
        for item_position, product_index in enumerate(product_indexes, start=1):
            quantity = 2 if (index + item_position) % 4 == 0 else 1
            unit_price = products[product_index]["unit_price"]
            line_total = unit_price * quantity
            total += line_total
            order_items.append(
                {
                    "id": seed_id(f"order-item:{index}:{product_index}"),
                    "order_id": seed_id(f"order:{index}"),
                    "product_id": products[product_index]["id"],
                    "quantity": quantity,
                    "unit_price": unit_price,
                    "line_total": line_total,
                    "created_at": created_at,
                }
            )

        totals[index] = total
        orders.append(
            {
                "id": seed_id(f"order:{index}"),
                "order_number": f"EC202608{index:04d}",
                "user_id": users[(index - 1) % 5]["id"],
                "status": status,
                "payment_status": payment_status,
                "total_amount": total,
                "paid_at": created_at + timedelta(hours=1)
                if payment_status != PaymentStatus.UNPAID
                else None,
                "cancelled_at": created_at + timedelta(hours=2)
                if status == OrderStatus.CANCELLED
                else None,
                "created_at": created_at,
                "updated_at": created_at,
            }
        )

    shipments: list[dict] = []
    for index in range(10, 22):
        order_created_at = SEED_EPOCH + timedelta(days=index)
        if index == 10:
            status = ShipmentStatus.PENDING
        elif index <= 13:
            status = ShipmentStatus.IN_TRANSIT
        elif index == 14:
            status = ShipmentStatus.EXCEPTION
        else:
            status = ShipmentStatus.DELIVERED
        shipments.append(
            {
                "id": seed_id(f"shipment:{index}"),
                "order_id": seed_id(f"order:{index}"),
                "carrier": "顺丰速运" if index % 2 == 0 else "京东物流",
                "tracking_number": f"SFJD202608{index:06d}",
                "status": status,
                "shipped_at": None
                if status == ShipmentStatus.PENDING
                else order_created_at + timedelta(days=1),
                "estimated_delivery_at": order_created_at + timedelta(days=4),
                "delivered_at": order_created_at + timedelta(days=3)
                if status == ShipmentStatus.DELIVERED
                else None,
                "created_at": order_created_at,
                "updated_at": order_created_at,
            }
        )

    refund_definitions = (
        (16, RefundStatus.REQUESTED, Decimal("50.00"), "商品与描述不符"),
        (17, RefundStatus.PENDING_REVIEW, Decimal("150.00"), "物流延误申请退款"),
        (18, RefundStatus.APPROVED, Decimal("80.00"), "部分商品包装破损"),
        (19, RefundStatus.REJECTED, Decimal("120.00"), "超过无理由退款范围"),
        (20, RefundStatus.COMPLETED, totals[20], "商品质量问题全额退款"),
    )
    refunds = [
        {
            "id": seed_id(f"refund:{order_index}"),
            "refund_number": f"RF202608{position:04d}",
            "order_id": seed_id(f"order:{order_index}"),
            "amount": amount,
            "reason": reason,
            "status": status,
            "requested_at": SEED_EPOCH + timedelta(days=order_index, hours=5),
            "completed_at": SEED_EPOCH + timedelta(days=order_index + 2)
            if status == RefundStatus.COMPLETED
            else None,
            "created_at": SEED_EPOCH + timedelta(days=order_index, hours=5),
            "updated_at": SEED_EPOCH + timedelta(days=order_index, hours=5),
        }
        for position, (order_index, status, amount, reason) in enumerate(
            refund_definitions, start=1
        )
    ]

    admin_id = users[-1]["id"]
    reviews = [
        {
            "id": seed_id("review:17"),
            "refund_id": seed_id("refund:17"),
            "reviewer_id": None,
            "status": ReviewStatus.PENDING,
            "priority": ReviewPriority.HIGH,
            "reviewer_note": None,
            "reviewed_at": None,
            "created_at": SEED_EPOCH + timedelta(days=17, hours=6),
            "updated_at": SEED_EPOCH + timedelta(days=17, hours=6),
        },
        {
            "id": seed_id("review:18"),
            "refund_id": seed_id("refund:18"),
            "reviewer_id": admin_id,
            "status": ReviewStatus.APPROVED,
            "priority": ReviewPriority.NORMAL,
            "reviewer_note": "核实图片后同意部分退款",
            "reviewed_at": SEED_EPOCH + timedelta(days=19),
            "created_at": SEED_EPOCH + timedelta(days=18, hours=6),
            "updated_at": SEED_EPOCH + timedelta(days=19),
        },
        {
            "id": seed_id("review:19"),
            "refund_id": seed_id("refund:19"),
            "reviewer_id": admin_id,
            "status": ReviewStatus.REJECTED,
            "priority": ReviewPriority.NORMAL,
            "reviewer_note": "订单已超过适用退款期限",
            "reviewed_at": SEED_EPOCH + timedelta(days=20),
            "created_at": SEED_EPOCH + timedelta(days=19, hours=6),
            "updated_at": SEED_EPOCH + timedelta(days=20),
        },
    ]

    return {
        "users": users,
        "products": products,
        "orders": orders,
        "order_items": order_items,
        "shipments": shipments,
        "refunds": refunds,
        "human_reviews": reviews,
    }


async def insert_seed_rows(session: AsyncSession, model, rows: list[dict]) -> None:
    await session.execute(insert(model).values(rows).on_conflict_do_nothing())


async def count_rows(session: AsyncSession, model) -> int:
    count = await session.scalar(select(func.count()).select_from(model))
    return int(count or 0)


async def seed_database(session: AsyncSession) -> SeedCounts:
    rows = build_seed_rows()
    for model, key in (
        (User, "users"),
        (Product, "products"),
        (Order, "orders"),
        (OrderItem, "order_items"),
        (Shipment, "shipments"),
        (Refund, "refunds"),
        (HumanReview, "human_reviews"),
    ):
        await insert_seed_rows(session, model, rows[key])

    knowledge_rows = build_knowledge_rows()
    if knowledge_rows:
        await insert_seed_rows(session, KnowledgeDocument, knowledge_rows)

    for email, password in (
        ("alice@example.com", "customer-password"),
        ("admin@example.com", "admin-password"),
    ):
        await session.execute(
            update(User)
            .where(User.email == email, User.password_hash.is_(None))
            .values(password_hash=hash_password(password))
        )

    return SeedCounts(
        users=await count_rows(session, User),
        products=await count_rows(session, Product),
        orders=await count_rows(session, Order),
        shipments=await count_rows(session, Shipment),
        refunds=await count_rows(session, Refund),
        reviews=await count_rows(session, HumanReview),
        knowledge_documents=await count_rows(session, KnowledgeDocument),
    )
