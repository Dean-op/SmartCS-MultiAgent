# ecommerce-ai-agent

面向电商售前、售后的 Multi-Agent 智能客服与业务执行系统。本仓库当前已完成 **M10：Conversation Memory + LangGraph Persistence**。

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
- Structured Supervisor Plan 与 Specialist 顺序协作、结果汇总
- `text-embedding-v4` + Milvus Dense Retrieval + Knowledge Agent
- Milvus BM25、Dense+BM25 RRF 与百炼 `qwen3-rerank`
- LangGraph `AsyncPostgresSaver` 持久化多轮 Conversation State
- SQLAlchemy 2.x 异步数据访问、Alembic Migration 和幂等 Seed Data
- User、Product、Order、OrderItem、Shipment、Refund、HumanReview 业务模型
- 面向后续 Tool 的 Repository、Service 和只读 DTO 边界

当前不包含长期记忆、摘要、消息裁剪、JWT、Redis Conversation、完整 Agent Evaluation 或 Observability。

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
EMBEDDING_MODEL=text-embedding-v4
EMBEDDING_DIMENSIONS=1024
KNOWLEDGE_COLLECTION=ecommerce_knowledge
KNOWLEDGE_TOP_K=3
BAILIAN_RERANK_BASE_URL=https://dashscope.aliyuncs.com/compatible-api/v1
RERANK_MODEL=qwen3-rerank
HYBRID_CANDIDATE_K=10
RRF_K=60
RERANK_MIN_SCORE=0.2
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

当前 assistant content 来自 `qwen3.8-27b`，响应 `mode` 为 `llm`。`conversation_id` 现在对应 LangGraph `thread_id`；下一次请求回传相同 UUID 时会恢复 PostgreSQL 中的 Graph State。

模型可调用三个只读 Tool，并可通过 Knowledge Agent 使用 Hybrid+Reranker 回答企业政策。业务 Tool 与 Agent 架构未改变，M10 仍不能修改订单或创建退款。

## Conversation Persistence

应用在 FastAPI lifespan 中打开官方 `AsyncPostgresSaver`、执行幂等 `setup()`，并将其传给 `StateGraph.compile(checkpointer=...)`。Checkpoint 使用现有 PostgreSQL 实例，由官方实现维护以下表：

- `checkpoints`
- `checkpoint_blobs`
- `checkpoint_writes`
- `checkpoint_migrations`

应用不会为这些表创建 Alembic Migration。每个请求只向已有 `messages` State 追加最新用户消息；没有新增 memory、profile 或 summary 字段。

显式运行真实多轮验证：

```bash
uv run python scripts/conversation_smoke_test.py
```

脚本验证同 conversation 的订单指代、从订单切换到退款 Agent，以及不同 conversation 的上下文隔离。

## LangGraph Workflow

M7 在简单 Route 保持不变的基础上增加 complex 与 Supervisor：

```text
START → router ─┬→ order_agent   → tools → order_agent   → END
                ├→ refund_agent  → tools → refund_agent  → END
                ├→ product_agent → tools → product_agent → END
                ├→ knowledge_agent → Dense Retrieval → LLM → END
                ├→ general_agent                           → END
                └→ complex → supervisor → specialist → tools → specialist
                             → supervisor_step → 下一个 specialist
                             → supervisor_final → END
```

Supervisor Plan 允许 order/refund/product/knowledge。Knowledge Agent 不持有业务 Tool，也不向 State 增加 retrieved documents；复杂路径继续复用现有 `agent_results`。

## Hybrid RAG

知识库包含 `knowledge/` 下 8 份中文 Markdown、24 个语义章节 Chunk。每个章节仍以 600 字符窗口和 80 字符 overlap 为上限。

显式执行入库：

```bash
uv run python scripts/ingest_knowledge.py
```

入库命令会明确重建 `ecommerce_knowledge`，因为 M9 Schema 新增中文 Analyzer、BM25 Function 和 `sparse_embedding`。Collection 同时使用 Dense `AUTOINDEX/COSINE` 与 Sparse `SPARSE_INVERTED_INDEX/BM25`。

运行真实 Dense Retrieval 与 Knowledge Agent smoke：

```bash
uv run python scripts/rag_smoke_test.py
uv run python scripts/conversation_smoke_test.py
```

运行 12 条 Retrieval 对比评估：

```bash
uv run python scripts/evaluate_retrieval.py
```

当前 Dense、Hybrid、Hybrid+Rerank 的 Hit@1/Hit@3 均为 1.00。Hybrid 改变了 Top-3 候选组成，但 `qwen3-rerank` 在部分查询中降低了非首位候选质量；详见 [evaluation/retrieval_results.md](evaluation/retrieval_results.md)。

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

显式验证真实 Supervisor 协作（会调用百炼并读取本地 PostgreSQL Seed）：

```bash
uv run python scripts/tool_calling_smoke_test.py
```

该脚本只验证一个简单订单 Route 和一个复杂订单+退款请求，检查 Supervisor Plan、顺序路径、隔离后的 Tool、参数、真实 Tool Result 和最终汇总。输出不包含 Key、Endpoint 或完整业务回答。

Provider 错误复用现有 API Error Contract，区分未配置、鉴权失败、限流/额度、timeout、连接失败、Structured Output 无效和其他 Provider 错误。客户端不会收到 SDK traceback、Key、Authorization Header 或 Provider 原始错误正文。

## 登录与退款审核

开发 Seed 提供 `alice@example.com / customer-password` 与
`admin@example.com / admin-password`。登录后将返回的 JWT 放入
`Authorization: Bearer <token>`；订单和退款 Tool 始终使用该可信用户身份。

退款申请继续通过 `/api/v1/chat` 发起。金额不超过 100 元且近 30 天有效退款少于
2 次时自动完成；其余合格请求返回 `pending_review`。管理员可使用：

```text
GET  /api/v1/reviews/pending
POST /api/v1/reviews/{review_id}/approve
POST /api/v1/reviews/{review_id}/reject
```

审批接口会恢复原 LangGraph Thread。显式真实模型退款验证会写入开发数据库：

```bash
uv run python scripts/refund_smoke_test.py
```

## Agent Evaluation

M13 使用 20 条小型数据集评估整个 Agent System，而不是重复 M9 的 Retriever
Hit@K。运行真实评估（会调用百炼、Milvus、本地 PostgreSQL 和已启动的 API）：

```bash
uv run python scripts/evaluate_agents.py
```

脚本输出 Router、Agent、Tool、参数、任务成功率和安全授权指标；固定基线记录在
`evaluation/agent_results.md`。评估失败项会保留，不以修改标注的方式制造满分。

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
uv run python scripts/ingest_knowledge.py
uv run python scripts/rag_smoke_test.py
uv run python scripts/refund_smoke_test.py
uv run python scripts/evaluate_agents.py
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

当前 Conversation 会保存完整 State，没有摘要、Token Budget、裁剪、保留期限或删除 API；长对话会持续增加模型上下文和 PostgreSQL checkpoint 历史。
