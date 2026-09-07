# ecommerce-ai-agent

面向电商售前、售后的 Multi-Agent 智能客服与业务执行系统。本仓库当前已完成 **M6：Router + Specialist Agents**。

## 当前能力

- `uv` 管理的 Python 3.12+ `src` 布局项目
- 最小 FastAPI 应用
- API liveness 与依赖 readiness 健康检查
- PostgreSQL、Redis、Milvus Standalone、etcd、MinIO 本地容器环境
- 命名卷持久化、自动化单元测试和运行态 smoke test
- `/api/v1` 版本化 API、稳定 Schema 和统一错误响应
- 基于百炼 OpenAI-compatible API 和 `qwen3.8-27b` 的真实 Chat
- JSON Object + Pydantic Structured Output
- 订单、商品、退款三个只读 Tool 与最小 Tool Calling 循环
- Structured Router、三个 Specialist 节点与隔离的 Tool 访问
- SQLAlchemy 2.x 异步数据访问、Alembic Migration 和幂等 Seed Data
- User、Product、Order、OrderItem、Shipment、Refund、HumanReview 业务模型
- 面向后续 Tool 的 Repository、Service 和只读 DTO 边界

当前不包含 Supervisor、Agent 协作、RAG、JWT、正式 Authorization、Redis Session、Celery Worker、Checkpointer、OpenTelemetry 或 Evaluation。

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

真实模型调用还需要配置：

```text
DASHSCOPE_API_KEY=
BAILIAN_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
LLM_MODEL=qwen3.8-27b
LLM_TIMEOUT_SECONDS=30
LLM_MAX_RETRIES=2
LLM_TEMPERATURE=0.2
LLM_MAX_COMPLETION_TOKENS=800
DEVELOPMENT_USER_EMAIL=alice@example.com
```

Base URL 必须与 Key 所属地域和业务空间匹配。Key 缺失时应用与 health 仍可启动，但 Chat 返回 `503 model_not_configured`。

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

当前 assistant content 来自 `qwen3.8-27b`，响应 `mode` 为 `llm`。客户端可在下一次请求中回传 `conversation_id`，但 M6 仍不保存会话状态。

模型可调用三个只读 Tool：按订单号查询当前用户订单、按 SKU 查询商品、按退款单号查询当前用户退款。Tool 只调用 M2 Service；订单与退款会使用服务端 `DEVELOPMENT_USER_EMAIL` 对应的可信开发身份进行 ownership 限定。客户端和模型都不能提供可信 `user_id`。M6 仍不能修改订单或创建退款。

## LangGraph Workflow

M6 在 M5 `StateGraph` 上增加 Structured Router 和三个 Specialist：

```text
START → router ─┬→ order_agent   → tools → order_agent   → END
                ├→ refund_agent  → tools → refund_agent  → END
                ├→ product_agent → tools → product_agent → END
                └→ general_agent                           → END
```

State 只包含追加式 `messages` 和 Router 产生的 `route`。每个 Specialist 只获得自己的单个 Tool Schema，Tool 节点还会在执行前再次校验 route 与 Tool 名称。Workflow 没有 Supervisor、协作、Checkpointer、Memory、Subgraph 或持久化。

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

## LLM 与 Structured Output 验证

默认 pytest 使用 Fake SDK，不调用外部模型。显式执行真实百炼验证：

```bash
uv run python scripts/llm_smoke_test.py
```

该脚本依次验证普通文本生成和 `MessageAssessment` Structured Output。结构化输出使用 JSON Object 模式，提示词给出 JSON Schema，再由 Pydantic 校验为 typed result。脚本只输出模型名、字符数量、类型和耗时，不打印 Key、Endpoint、Prompt 或完整回复。真实调用会消耗额度。

显式验证真实 Router 与 Specialist Tool Calling（会调用百炼并读取本地 PostgreSQL Seed）：

```bash
uv run python scripts/tool_calling_smoke_test.py
```

该脚本验证 order、refund、product、general 四类 Route 和跨用户 ownership，并检查实际 Specialist 路径、隔离后的 Tool、参数、真实 Tool Result 和最终回答。输出不包含 Key、Endpoint 或完整业务回答。

Provider 错误复用现有 API Error Contract，区分未配置、鉴权失败、限流/额度、timeout、连接失败、Structured Output 无效和其他 Provider 错误。客户端不会收到 SDK traceback、Key、Authorization Header 或 Provider 原始错误正文。

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
uv run python scripts/tool_calling_smoke_test.py
```

真实模型验收需要显式运行：

```bash
uv run python scripts/llm_smoke_test.py
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

### Chat 返回 provider_rate_limited

检查百炼模型额度、限流和“免费额度用完即停”设置。普通基础设施 smoke 不调用真实模型，可独立验证 Docker 与 API 基础状态。

## 后续开发边界

Supervisor、跨 Agent 协作、RAG、Celery 和可观测性将在后续里程碑中按设计方案逐步加入。后续编排可直接复用当前 Route Schema、Router、三个 Specialist、Tool Isolation、`BusinessTools.run` 和 M2 Service。
