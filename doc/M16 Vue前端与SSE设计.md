# M16 Vue 前端、SSE 流式会话与知识库管理设计

## 目标

在现有 FastAPI、LangGraph、PostgreSQL 和 Milvus 上增加一个同源 Vue 3 SPA，覆盖用户聊天、会话历史、知识库管理和退款审核。前端必须展示真实 SSE Token、Provider reasoning content、Agent/Tool 状态和 Markdown，不新增独立前端服务。

## 关键决策

- Vue 3 + TypeScript + Vite + Vue Router；不使用 Pinia、Axios 或 UI 组件库。
- `md-editor-v3 6.5.6` 同时承担知识编辑和聊天 Markdown 预览，启用 XSSPlugin。
- Vite 由 Docker Node Stage 构建，静态文件复制到最终 Python 镜像并由 FastAPI 同源托管。
- SSE 使用 POST + fetch ReadableStream，事件分为 conversation、status、reasoning_delta、delta、done、error。
- Structured Router、Supervisor Plan 和 Tool Selection 继续非流式且关闭 thinking；最终自然语言生成开启 thinking 并流式输出。
- LangGraph Checkpoint 继续负责工作流恢复；Conversation/Message 表只提供产品级列表和历史查询。
- PostgreSQL KnowledgeDocument 是运行时文档源；仓库 Markdown 只作为幂等 Seed。

## 数据流

```text
Vue fetch stream
→ FastAPI SSE
→ ChatService
→ LangGraph custom/updates stream
→ Bailian reasoning_content/content
→ reasoning_delta/delta
→ ConversationMessage persistence
```

```text
Admin Markdown Editor
→ KnowledgeDocument
→ Chunk 600/80
→ text-embedding-v4
→ Milvus Dense + BM25
→ RRF + qwen3-rerank
→ Knowledge Agent / Retrieval Playground
```

## 安全与边界

- 会话与历史按 current_user ownership 查询，跨用户返回404。
- 所有知识管理与退款审核 API 仅允许 admin。
- reasoning 不回传给模型，不记录系统 Prompt 或 Tool 参数。
- Markdown 通过 XSSPlugin 过滤，前端包含公开 fenced-code payload 回归测试。
- 不实现 WebSocket、图片托管、文档版本、会话删除、Celery 或独立前端部署。
