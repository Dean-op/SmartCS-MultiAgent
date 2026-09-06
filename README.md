# ecommerce-ai-agent

面向电商售前、售后的 Multi-Agent 智能客服与业务执行系统。本仓库当前已完成 **M2：PostgreSQL 业务数据层**。

## 当前能力

- `uv` 管理的 Python 3.12+ `src` 布局项目
- 最小 FastAPI 应用
- API liveness 与依赖 readiness 健康检查
- PostgreSQL、Redis、Milvus Standalone、etcd、MinIO 本地容器环境
- 命名卷持久化、自动化单元测试和运行态 smoke test
- `/api/v1` 版本化 API、稳定 Schema 和统一错误响应
- 不依赖 LLM 的 Mock Chat API
- SQLAlchemy 2.x 异步数据访问、Alembic Migration 和幂等 Seed Data
- User、Product、Order、OrderItem、Shipment、Refund、HumanReview 业务模型
- 面向后续 Tool 的 Repository、Service 和只读 DTO 边界

当前不包含 Agent、LLM、RAG、JWT、Authorization、Redis Session、Celery Worker、LangGraph、OpenTelemetry 或 Evaluation。

## 环境要求

- Python 3.12 或 3.13
- [uv](https://docs.astral.sh/uv/)
- Docker Desktop 或 Docker Engine
- Docker Compose v2+
- 建议为 Docker 分配至少 6 GB 内存；首次启动需要拉取 Milvus 等较大镜像

## 配置

复制环境变量示例：

```powershell
Copy-Item .env.example .env
```

Linux 或 macOS：

```bash
cp .env.example .env
```

`.env` 不会进入 Git。示例密码只适用于本地开发；共享环境或生产环境必须替换。

在 Docker Compose 中，API 使用 `postgres`、`redis`、`milvus` 等 Service Name 访问依赖。`.env` 中的 `localhost` 默认值用于在宿主机直接运行 API。

## 本机开发

安装锁定的全部依赖：

```bash
uv sync --frozen --all-groups
```

完整 pytest 包含真实 PostgreSQL 集成测试，请先确保 Compose 中 PostgreSQL healthy。运行质量检查和测试：

```bash
uv run ruff check .
uv run pytest
```

如果基础设施已由 Docker 启动，也可以在宿主机运行 API：

```bash
uv run uvicorn ecommerce_ai_agent.main:create_app --factory --reload
```

## 启动完整本地环境

构建并后台启动：

```bash
docker compose up -d --build
```

查看服务状态：

```bash
docker compose ps
```

跟踪全部日志：

```bash
docker compose logs -f
```

只查看 API 或 Milvus 日志：

```bash
docker compose logs -f api
docker compose logs -f milvus
```

首次拉取镜像和启动 Milvus 可能需要数分钟。

## 健康检查

浏览器或命令行访问：

- API 存活：<http://localhost:8000/health/live>
- API 就绪：<http://localhost:8000/health/ready>
- Milvus 管理健康端点：<http://localhost:9091/healthz>
- MinIO Console：<http://localhost:9001>

运行跨平台 smoke test：

```bash
uv run python scripts/smoke_test.py
```

readiness 会实际连接 PostgreSQL、执行 Redis `PING`，并调用 Milvus 管理健康端点。它不会创建业务表、LangGraph Checkpoint 或 Milvus Collection。

## Chat API

发送一条消息：

```bash
curl -X POST http://localhost:8000/api/v1/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"我的订单什么时候到？"}'
```

请求字段：

- `message`：必填字符串，去除首尾空白后长度为 1～4000。
- `conversation_id`：可选 UUID，只作为会话关联标识，不代表可信用户身份。
- 不允许额外字段；身份认证将在后续里程碑实现。

当前返回 Mock assistant message，不调用模型或外部服务。客户端可在下一次请求中回传 `conversation_id`，但 M1 不保存会话状态。

所有 API 错误统一为：

```json
{
  "error": {
    "code": "validation_error",
    "message": "Request validation failed",
    "details": [
      {
        "field": "body.message",
        "message": "String should have at least 1 character",
        "type": "string_too_short"
      }
    ]
  }
}
```

Swagger UI：<http://localhost:8000/docs>，OpenAPI Schema：<http://localhost:8000/openapi.json>。

## PostgreSQL 业务数据

业务 Schema 只通过 Alembic 管理，应用启动不会调用 `create_all`。升级到最新版本：

```bash
uv run alembic upgrade head
uv run alembic current
uv run alembic check
```

初始化或补齐可重复使用的开发数据：

```bash
uv run python scripts/seed_data.py
```

Seed 可重复运行且不会产生重复记录，当前包含：

- 6 个用户，包括 5 个 customer 和 1 个 admin
- 12 个商品
- 24 个订单及订单项
- 12 条物流、5 条退款、3 条人工审核记录
- 待支付、处理中、运输中、已完成、已取消等业务场景

业务金额在 PostgreSQL 中使用 `NUMERIC(12,2)`，在 Python 中使用 `Decimal`。状态使用 PostgreSQL Named Enum，不接受任意字符串。

完整测试会安全地创建并删除独立的 `ecommerce_agent_test` 数据库。测试保护规则要求数据库名必须以 `_test` 结尾，不会清理开发数据库。

M2 不增加用户、订单等公共 CRUD API。未来 API 或 Tool 应调用 `UserService`、`CatalogService`、`OrderService`、`RefundService`，不能直接访问 ORM。

## 停止与清理

停止并删除容器和网络，但保留数据卷：

```bash
docker compose down
```

再次启动后，PostgreSQL、Redis、etcd、MinIO 和 Milvus 数据仍会保留。

彻底删除本地数据：

```bash
docker compose down -v
```

`down -v` 会删除所有 M0 命名卷，操作不可恢复，请只在明确需要重置环境时执行。

## 常用验证命令

```bash
uv lock --check
uv sync --frozen --all-groups
uv run ruff format --check .
uv run ruff check .
uv run alembic upgrade head
uv run alembic check
uv run python scripts/seed_data.py
uv run pytest
docker compose config --quiet
docker compose build api
docker compose up -d
docker compose ps
uv run python scripts/smoke_test.py
```

## 常见问题

### 端口已被占用

在 `.env` 中调整 `API_HOST_PORT`、`POSTGRES_HOST_PORT`、`REDIS_HOST_PORT`、`MILVUS_HOST_PORT`、`MILVUS_MANAGEMENT_HOST_PORT`、`MINIO_API_HOST_PORT` 或 `MINIO_CONSOLE_HOST_PORT`。

### 服务长时间处于 starting

先查看 `docker compose ps` 和目标服务日志。Milvus 首次启动耗时通常最长；如果容器被系统杀死，应提高 Docker Desktop 的内存上限。

### readiness 返回 503

响应中的 `dependencies` 会标记不可用的依赖。通过 `docker compose logs <service>` 查看对应服务日志；接口不会返回连接密码或原始异常。

### 修改 `.env` 后配置未生效

重新创建容器：

```bash
docker compose up -d --force-recreate
```

## 后续开发边界

Agent、LangGraph、Tool Calling、RAG、Celery 和可观测性将在后续里程碑中按设计方案逐步加入。M2 Service 是未来 Tool 访问业务数据的唯一入口，M1 Chat Service 仍是后续 LangGraph Workflow 的替换边界。
