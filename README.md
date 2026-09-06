# ecommerce-ai-agent

面向电商售前、售后的 Multi-Agent 智能客服与业务执行系统。本仓库当前完成范围仅为 **M0：工程骨架与本地开发基础设施**。

## 当前能力

- `uv` 管理的 Python 3.12+ `src` 布局项目
- 最小 FastAPI 应用
- API liveness 与依赖 readiness 健康检查
- PostgreSQL、Redis、Milvus Standalone、etcd、MinIO 本地容器环境
- 命名卷持久化、自动化单元测试和运行态 smoke test

M0 不包含 Agent、LLM、RAG、业务模型、JWT、Celery Worker、LangGraph、OpenTelemetry 或 Evaluation。

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

运行质量检查和测试：

```bash
uv run ruff check .
uv run pytest
```

如果基础设施已由 Docker 启动，也可以在宿主机运行 API：

```bash
uv run uvicorn ecommerce_ai_agent.main:create_app --factory --reload
```

## 启动完整 M0 环境

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
uv run ruff check .
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

Agent、LangGraph、业务数据模型、RAG、Celery 和可观测性将在后续里程碑中按设计方案逐步加入。不要在 M0 中创建占位业务模块或空基础设施。
