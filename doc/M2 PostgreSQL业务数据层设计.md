# M2 PostgreSQL 业务数据层设计

## 1. 文档状态

- 项目：`ecommerce-ai-agent`
- 里程碑：M2——PostgreSQL 业务数据层
- 状态：已确认，待实施
- 日期：2026-09-06

## 2. 目标与边界

M2 建立订单查询、物流查询、商品查询、退款查询和后续人工退款审核所需的真实业务数据基础。业务访问路径固定为：

```text
Future API / Tool
        ↓
     Service
        ↓
   Repository
        ↓
 SQLAlchemy 2.x
        ↓
   PostgreSQL
```

Agent、Tool 或 API 不直接访问 ORM 和数据库。M2 不实现写业务、认证、风控、Agent、LLM、LangGraph、Redis Session、Milvus Collection 或新的公共 CRUD API。

PostgreSQL 的 `public` Schema 存放业务表。未来 LangGraph Checkpoint 使用独立 Schema，不在 M2 创建。

## 3. 技术方案选择

采用以下组合：

- PostgreSQL UUID 主键，由应用生成 UUID v4；Seed 使用 UUID v5 生成确定性标识。
- Python `str, Enum` 与 PostgreSQL Named Enum 表达有限状态。
- PostgreSQL `NUMERIC(12, 2)` 与 Python `Decimal` 表达人民币金额。
- SQLAlchemy 2.x Typed Declarative ORM 与 `asyncpg` 异步驱动。
- `AsyncSession` per task，`async_sessionmaker(expire_on_commit=False)` 创建会话。
- 具体 Repository 和 Service，不增加 BaseRepository、GenericService 或 Unit of Work 框架。
- Repository 返回 ORM aggregate，Service 映射为只读 Pydantic DTO，未来 Tool 不接触 ORM。
- Alembic 是正式 Schema 管理入口；应用启动时不调用 `create_all`。

## 4. 状态体系

数据库存储以下小写 Enum value：

| 类型 | 值 |
| --- | --- |
| `user_role` | `customer`, `admin` |
| `order_status` | `pending_payment`, `processing`, `shipped`, `completed`, `cancelled` |
| `payment_status` | `unpaid`, `paid`, `partially_refunded`, `refunded` |
| `shipment_status` | `pending`, `in_transit`, `delivered`, `exception` |
| `refund_status` | `requested`, `pending_review`, `approved`, `rejected`, `processing`, `completed`, `cancelled` |
| `review_status` | `pending`, `approved`, `rejected` |
| `review_priority` | `normal`, `high` |

订单状态描述订单履约生命周期，支付状态描述资金状态，两者分开。物流、退款和审核拥有各自状态，不复用任意字符串。

## 5. 通用字段约定

- 主键：PostgreSQL `UUID`，不暴露数据库增长规模。
- `created_at`、`updated_at`：`TIMESTAMP WITH TIME ZONE`，数据库默认 `now()`，应用统一使用 UTC。
- `updated_at`：ORM 更新时使用数据库 `now()`；M2 不引入数据库触发器。
- 外部编号：订单号、退款号和 SKU 使用可读字符串并建立唯一约束。
- 文本：业务必填文本增加非空白 Check Constraint。
- 不实现软删除字段；业务事实默认保留，M2 也不提供删除能力。

## 6. 实体设计

### 6.1 users

| 字段 | 类型 | 约束 |
| --- | --- | --- |
| `id` | UUID | PK |
| `email` | VARCHAR(320) | NOT NULL |
| `password_hash` | VARCHAR(255) | NULL，认证阶段预留 |
| `role` | `user_role` | NOT NULL，默认 `customer` |
| `is_active` | BOOLEAN | NOT NULL，默认 true |
| `created_at` | TIMESTAMPTZ | NOT NULL |
| `updated_at` | TIMESTAMPTZ | NOT NULL |

约束与索引：

- `lower(email)` 唯一索引，保证 Email 大小写不重复。
- Email 必须为非空白；完整 Email 语法验证属于应用层。

### 6.2 products

| 字段 | 类型 | 约束 |
| --- | --- | --- |
| `id` | UUID | PK |
| `sku` | VARCHAR(64) | NOT NULL, UNIQUE |
| `name` | VARCHAR(200) | NOT NULL |
| `description` | TEXT | NULL |
| `unit_price` | NUMERIC(12,2) | NOT NULL，`>= 0` |
| `is_active` | BOOLEAN | NOT NULL，默认 true |
| `created_at` | TIMESTAMPTZ | NOT NULL |
| `updated_at` | TIMESTAMPTZ | NOT NULL |

SKU 和名称必须为非空白。产品当前只支持人民币，不增加尚无使用场景的多币种体系。

### 6.3 orders

| 字段 | 类型 | 约束 |
| --- | --- | --- |
| `id` | UUID | PK |
| `order_number` | VARCHAR(32) | NOT NULL, UNIQUE |
| `user_id` | UUID | NOT NULL, FK `users.id`, RESTRICT |
| `status` | `order_status` | NOT NULL |
| `payment_status` | `payment_status` | NOT NULL |
| `total_amount` | NUMERIC(12,2) | NOT NULL，`>= 0` |
| `paid_at` | TIMESTAMPTZ | NULL |
| `cancelled_at` | TIMESTAMPTZ | NULL |
| `created_at` | TIMESTAMPTZ | NOT NULL |
| `updated_at` | TIMESTAMPTZ | NOT NULL |

索引：`(user_id, created_at)`，支持用户订单列表；唯一订单号索引支持订单查询。`user_id` 是 ownership 的唯一可信数据来源。

### 6.4 order_items

| 字段 | 类型 | 约束 |
| --- | --- | --- |
| `id` | UUID | PK |
| `order_id` | UUID | NOT NULL, FK `orders.id`, CASCADE |
| `product_id` | UUID | NOT NULL, FK `products.id`, RESTRICT |
| `quantity` | INTEGER | NOT NULL，`> 0` |
| `unit_price` | NUMERIC(12,2) | NOT NULL，`>= 0` |
| `line_total` | NUMERIC(12,2) | NOT NULL，`>= 0` |
| `created_at` | TIMESTAMPTZ | NOT NULL |

`unit_price` 是下单时价格快照，不随产品价格变化。唯一约束 `(order_id, product_id)`，同一订单中的相同产品合并为一个订单项。`line_total = unit_price × quantity` 由写入用例计算；数据库负责范围约束，不增加跨字段舍入表达式。

### 6.5 shipments

| 字段 | 类型 | 约束 |
| --- | --- | --- |
| `id` | UUID | PK |
| `order_id` | UUID | NOT NULL, UNIQUE, FK `orders.id`, CASCADE |
| `carrier` | VARCHAR(100) | NOT NULL |
| `tracking_number` | VARCHAR(100) | NOT NULL |
| `status` | `shipment_status` | NOT NULL |
| `shipped_at` | TIMESTAMPTZ | NULL |
| `estimated_delivery_at` | TIMESTAMPTZ | NULL |
| `delivered_at` | TIMESTAMPTZ | NULL |
| `created_at` | TIMESTAMPTZ | NOT NULL |
| `updated_at` | TIMESTAMPTZ | NOT NULL |

一个订单最多一个 Shipment。唯一约束 `(carrier, tracking_number)`；carrier 和 tracking number 必须为非空白。

### 6.6 refunds

| 字段 | 类型 | 约束 |
| --- | --- | --- |
| `id` | UUID | PK |
| `refund_number` | VARCHAR(32) | NOT NULL, UNIQUE |
| `order_id` | UUID | NOT NULL, FK `orders.id`, RESTRICT |
| `amount` | NUMERIC(12,2) | NOT NULL，`> 0` |
| `reason` | VARCHAR(500) | NOT NULL |
| `status` | `refund_status` | NOT NULL |
| `requested_at` | TIMESTAMPTZ | NOT NULL |
| `completed_at` | TIMESTAMPTZ | NULL |
| `created_at` | TIMESTAMPTZ | NOT NULL |
| `updated_at` | TIMESTAMPTZ | NOT NULL |

索引：`(order_id, created_at)`。退款金额不得超过订单可退款金额属于跨记录业务规则，M2 不用不可靠的单行 Check Constraint 模拟，后续由 RefundService 写用例和事务保证。

### 6.7 human_reviews

| 字段 | 类型 | 约束 |
| --- | --- | --- |
| `id` | UUID | PK |
| `refund_id` | UUID | NOT NULL, UNIQUE, FK `refunds.id`, CASCADE |
| `reviewer_id` | UUID | NULL, FK `users.id`, SET NULL |
| `status` | `review_status` | NOT NULL，默认 `pending` |
| `priority` | `review_priority` | NOT NULL，默认 `normal` |
| `reviewer_note` | VARCHAR(1000) | NULL |
| `reviewed_at` | TIMESTAMPTZ | NULL |
| `created_at` | TIMESTAMPTZ | NOT NULL |
| `updated_at` | TIMESTAMPTZ | NOT NULL |

一个 Refund 最多一个 HumanReview。M2 只表达持久化结构，不判断风险、不执行 approve/reject、不触发 LangGraph。

## 7. ORM 关系与加载策略

```text
User 1 ─── N Order
Order 1 ─── N OrderItem N ─── 1 Product
Order 1 ─── 0..1 Shipment
Order 1 ─── N Refund
Refund 1 ─── 0..1 HumanReview
HumanReview N ─── 0..1 User(reviewer)
```

双向关系使用 `back_populates`。Repository 查询 Order aggregate 时使用 `selectinload` 显式加载 Items→Product、Shipment、Refunds→HumanReview，Service 映射 DTO 后不再依赖活动 Session。禁止在异步调用路径中依赖隐式 lazy load。

## 8. 代码组织

```text
src/ecommerce_ai_agent/
├── database.py
├── models/
│   ├── base.py
│   ├── enums.py
│   ├── user.py
│   ├── product.py
│   ├── order.py
│   ├── shipment.py
│   └── refund.py
├── repositories/
│   ├── user.py
│   ├── product.py
│   ├── order.py
│   └── refund.py
└── services/
    ├── data_types.py
    ├── user.py
    ├── catalog.py
    ├── order.py
    └── refund.py

alembic/
├── env.py
├── script.py.mako
└── versions/
    └── <revision>_create_business_schema.py

alembic.ini
scripts/seed_data.py
tests/integration/
```

不新增 HTTP 业务路由，M1 Chat Contract 保持不变。

## 9. Session 与事务边界

`database.py` 只负责：

- 从现有 `Settings` 创建隐藏密码的 SQLAlchemy PostgreSQL URL。
- 创建 `AsyncEngine`，启用 `pool_pre_ping`。
- 创建 `async_sessionmaker[AsyncSession]`，使用 `expire_on_commit=False`。

每个异步请求、脚本任务或 Tool 调用创建自己的 Session，不能跨并发任务共享。

Repository：

- 接收当前 `AsyncSession`。
- 只执行查询、add、flush。
- 不调用 commit、rollback 或 close。

Service：

- 接收当前 `AsyncSession` 并组合具体 Repository。
- 负责 ownership 范围、业务语义和 ORM→DTO 映射。
- M2 的查询方法不产生写事务。

调用方：

- 读取：`async with session_factory() as session`。
- 写入/Seed：`async with session_factory.begin() as session`，成功 commit，异常 rollback，并自动关闭 Session。

## 10. Repository 与 Service 能力

### User

- `UserRepository.get_by_id`
- `UserRepository.get_by_email`
- `UserService.get_user`
- `UserService.get_user_by_email`

### Product

- `ProductRepository.get_by_id`
- `ProductRepository.get_by_sku`
- `CatalogService.get_product`
- `CatalogService.get_product_by_sku`

### Order

- `OrderRepository.get_by_number`：加载完整 Order aggregate。
- `OrderRepository.get_for_user`：SQL 查询同时约束 `order_number` 和 `user_id`。
- `OrderRepository.list_by_user`：按 `created_at DESC`。
- `OrderService.get_order_by_number`
- `OrderService.get_order_for_user`
- `OrderService.list_user_orders`

Order DTO 包含 items、每项产品信息、可选 shipment 和 refunds，因此可以验证查询订单项、商品、物流和退款关系。`get_order_for_user` 是后续 customer Tool 的默认入口；不属于当前用户时返回 `None`，避免先查订单再在内存判断 ownership。

### Refund

- `RefundRepository.get_by_number`：加载可选 HumanReview。
- `RefundRepository.list_by_order`
- `RefundService.get_refund_by_number`
- `RefundService.list_order_refunds`

## 11. DTO 边界

Service 返回只读 Pydantic DTO：

- `UserData`
- `ProductData`
- `OrderItemData`（嵌套 `ProductData`）
- `ShipmentData`
- `HumanReviewData`
- `RefundData`
- `OrderData`（嵌套 items/shipment/refunds）

DTO 使用 `from_attributes=True` 从已 eager-load 的 ORM aggregate 构建，不公开 SQLAlchemy state。金额保持 `Decimal`，时间保持 timezone-aware `datetime`，状态保持对应 Enum。

## 12. Alembic 方案

- 新增 `sqlalchemy>=2.0,<2.1` 与 `alembic>=1.18,<2`，继续使用已有 `asyncpg`。
- Alembic 使用 async 模板；连接 URL 由 `Settings` 构造，不写入 `alembic.ini`。
- `target_metadata = Base.metadata`，导入全部业务 Models。
- 首个 Migration 显式创建 7 个 Named Enum、7 张业务表、FK、Check、Unique 和 Index。
- upgrade 顺序：Enums → users/products/orders → order_items/shipments/refunds → human_reviews。
- downgrade 顺序完全反向：表和索引 → Enum types。
- 不在应用启动、测试或 Seed 中调用 `Base.metadata.create_all`。

验收在独立空数据库执行：`upgrade head → inspect → downgrade base → inspect → upgrade head`，证明正反迁移可用。

## 13. Seed Data

Seed 使用固定业务内容、固定业务时间和 UUID v5，不生成随机数据。使用 PostgreSQL `INSERT ... ON CONFLICT DO NOTHING`，重复执行不重复插入。

### 13.1 用户

6 个：

- 5 个 active customer，覆盖不同订单 ownership。
- 1 个 active admin，用作 HumanReview reviewer。
- `password_hash = NULL`，不伪造可登录密码。

### 13.2 商品

12 个有意义 SKU，覆盖手机配件、数码设备、家居和办公用品；价格为两位小数 Decimal。

### 13.3 订单

24 个订单，每个 customer 至少 4 个，状态覆盖：

- 4 个 `pending_payment/unpaid`
- 5 个 `processing/paid`
- 5 个 `shipped/paid`
- 7 个 `completed/paid|partially_refunded|refunded`
- 3 个 `cancelled/unpaid`

订单包含 1～3 个订单项，`total_amount` 等于行金额之和。

### 13.4 物流、退款与审核

- 12 个 Shipment，覆盖 pending、in_transit、delivered、exception。
- 5 个 Refund，覆盖 requested、pending_review、approved、rejected、completed。
- 3 个 HumanReview，覆盖 pending、approved、rejected，其中已完成审核记录 admin reviewer。

## 14. 测试数据库方案

测试默认使用 `ecommerce_agent_test`，不复用开发数据库。测试基础设施在任何 drop/create 前必须验证数据库名严格以 `_test` 结尾。

测试 Session fixture 流程：

1. 连接 PostgreSQL maintenance database `postgres`。
2. 终止目标测试数据库残留连接。
3. `DROP DATABASE IF EXISTS ecommerce_agent_test`。
4. `CREATE DATABASE ecommerce_agent_test`。
5. 临时将 Alembic URL 指向测试库。
6. 执行 `upgrade head → downgrade base → upgrade head`。
7. 执行 Seed。
8. 运行只读 Repository/Service 集成测试。
9. 关闭 Engine 后删除测试数据库。

pytest 不使用 SQLite 替代 PostgreSQL，因为 UUID、Named Enum、Numeric、TIMESTAMPTZ、PostgreSQL upsert 和 Migration 都需要真实方言验证。运行完整 pytest 前需要 Docker PostgreSQL healthy；连接失败应给出明确提示而不是静默 skip。

## 15. 自动化测试范围

- Migration 从空库创建 7 张业务表与 7 个 Enum types。
- Migration downgrade 删除全部 M2 表与 Enum，随后 upgrade 可恢复。
- Seed 首次执行得到 6 users、12 products、24 orders 和约定关联数据。
- Seed 第二次执行数量不变。
- 金额从 PostgreSQL 读取为 `Decimal`，无 float。
- User 与 Product 查询。
- 按订单号查询完整 Order aggregate。
- 用户订单列表和 ownership-scoped 查询。
- 不同用户无法通过 `get_order_for_user` 读到不属于自己的订单。
- Order Items 嵌套 Product 正确。
- Order Shipment 正确。
- Order Refunds 与 HumanReview 正确。
- Service 返回 DTO，不返回 ORM 实例。
- M0 health 与 M1 Chat/OpenAPI 全部回归。

## 16. 运行与验收流程

```text
uv lock --check
uv sync --frozen --all-groups
uv run ruff format --check .
uv run ruff check .
docker compose up -d --build --wait
uv run alembic upgrade head
uv run python scripts/seed_data.py
uv run python scripts/seed_data.py       # 验证幂等
uv run pytest
uv run python scripts/smoke_test.py
```

额外通过 SQL/Service 查询确认 ownership、Items→Product、Shipment、Refund 和 Review 关系。最终检查工作区、Secret、Migration、Seed、Tests 和 M2+ 禁止范围。

## 17. 不增加 HTTP CRUD API 的原因

M2 的目标是建立数据与业务访问边界，不是公开数据管理接口。为测试而添加 `/users`、`/orders` 等公共 CRUD 会提前引入认证、授权和 API Contract。M2 使用真实 PostgreSQL 集成测试和 Seed 查询脚本验证业务能力，M1 API 保持原样。

## 18. 风险与处理

### 18.1 PostgreSQL 原生 Enum 演进

Named Enum 提供强约束，但新增、重命名值需要显式 Migration。状态数量小且业务含义稳定，约束收益高于迁移成本；Migration 必须审查 Enum 变更。

### 18.2 updated_at

M2 不为 `updated_at` 引入数据库触发器。所有应用写入必须经过 Service/Session，让 ORM `onupdate` 生效；如果未来存在外部 SQL 写入，再评估触发器。

### 18.3 测试数据库删除

测试辅助代码只允许删除严格匹配 `_test` 后缀的数据库，并在连接目标与预期不一致时快速失败，避免误删开发数据。

### 18.4 Seed 与生产

Seed 是开发测试数据，不在 API 启动时自动执行。生产部署必须单独运行 Migration，且不得运行开发 Seed。

## 19. M2 完成判定

只有以下条件全部满足才判定 M2 完成：

1. 七个业务实体、状态、关系、约束和索引由 Alembic 管理。
2. 空测试库 upgrade、downgrade、再次 upgrade 全部成功。
3. Seed 数据数量和场景满足要求，重复执行幂等。
4. Repository 与 Service 能完成全部指定查询，Service 不暴露 ORM。
5. ownership 查询在 SQL 层约束 user_id。
6. 金额使用 NUMERIC/Decimal，时间使用 timezone-aware datetime/TIMESTAMPTZ。
7. Ruff format/lint 和完整 pytest 通过。
8. Compose 六服务 healthy，M0 smoke 与 M1 API/Swagger 回归通过。
9. 没有引入 M2 禁止能力或公共 CRUD API。
10. Migration、Seed、Tests、README 和开发记录进入独立 Git Commit，工作区干净且无 Secret。

## 20. 参考依据

- SQLAlchemy AsyncIO：<https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html>
- SQLAlchemy Session：<https://docs.sqlalchemy.org/en/20/orm/session_basics.html>
- SQLAlchemy Declarative 与 Named Enum：<https://docs.sqlalchemy.org/en/20/orm/declarative_tables.html>
- SQLAlchemy PostgreSQL 方言：<https://docs.sqlalchemy.org/en/20/dialects/postgresql.html>
- Alembic Autogenerate：<https://alembic.sqlalchemy.org/en/latest/autogenerate.html>
