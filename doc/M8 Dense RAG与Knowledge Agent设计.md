# M8 Dense RAG 与 Knowledge Agent 设计

## 1. 目标与边界

M8 只建立最基础的 Dense RAG：Markdown 政策文档经过切片和 `text-embedding-v4` 向量化后写入现有 Milvus，由 Knowledge Agent 检索 Top-K Chunk，并让 `qwen3.8-27b` 基于检索结果回答。

本阶段新增 knowledge Route 和 Knowledge Agent，但不增加业务 Tool，不实现 BM25、Sparse/Hybrid Search、RRF、Reranker、Query Rewrite、HyDE、Memory、Checkpointer、JWT、退款写操作或 Evaluation Framework。

## 2. 方案选择

采用具体实现直连方案：

- 现有百炼模型边界增加批量 Dense Embedding 方法。
- 新增一个具体 `KnowledgeBase`，直接负责 Chunk、Milvus 入库和 Dense Search。
- Knowledge Agent 作为现有 LangGraph 中的普通节点调用 `KnowledgeBase.search`。
- 不使用 LangChain VectorStore，不创建 Embedding Provider Factory、Retriever 层级、VectorStore Registry 或通用 RAG Framework。

该方案保留本阶段需要学习的 Embedding、Milvus Schema、Index 和 Search 细节，同时避免为单一 Provider 和单一 Collection 建立抽象框架。

## 3. 数据流

入库：

```text
Markdown → UTF-8 Load → Fixed-size Chunk → text-embedding-v4
         → Milvus ecommerce_knowledge Collection
```

问答：

```text
Question → text-embedding-v4 → Milvus COSINE Search → Top-K Chunks
         → Knowledge Agent Prompt → qwen3.8-27b → Grounded Answer + Sources
```

## 4. Knowledge Documents 与 Chunk

提供 4 个中文 Markdown 文档：

- `refund-policy.md`
- `shipping-policy.md`
- `after-sales-policy.md`
- `payment-policy.md`

Chunk 使用简单字符窗口：

- `chunk_size=600`
- `overlap=80`
- 跳过纯空白 Chunk
- 保留 `content`、`source` 和稳定 `chunk_id`
- `chunk_id` 由 source、顺序和内容生成确定性摘要，重复入库不会产生重复主键

不引入 Markdown AST、Tokenizer 或第三方文档加载器。政策文档规模小，字符窗口足以验证完整链路。

## 5. Embedding

- Provider：阿里云百炼 OpenAI-compatible API
- Model：`text-embedding-v4`
- Dimension：1024
- Encoding：float
- 批量输入，单次入库尽量一次完成
- API Key 与 Base URL 复用现有百炼环境变量
- timeout 与 retry 复用现有 SDK 配置

百炼官方说明 `text-embedding-v4` 支持自定义 64～2048 维，并推荐 1024 维作为通用检索的性能与成本平衡点：<https://help.aliyun.com/zh/model-studio/embedding?disableWebsiteRedirect=true>。

## 6. Milvus Collection

Collection：`ecommerce_knowledge`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `chunk_id` | VARCHAR(64) | 主键，不自动生成 |
| `source` | VARCHAR(256) | Markdown 文件名 |
| `content` | VARCHAR(4096) | Chunk 正文 |
| `embedding` | FLOAT_VECTOR(1024) | Dense Vector |

设置：

- Dynamic Field：关闭
- Vector Index：`AUTOINDEX`
- Metric：`COSINE`
- Shard：Milvus Standalone 默认单分片

使用 `MilvusClient` 的自定义 Schema 和 Index 参数：<https://milvus.io/api-reference/pymilvus/v2.6.x/MilvusClient/Collections/create_collection.md>。

入库脚本先确保 Collection 存在，再用确定性 `chunk_id` upsert Chunk。不会在 API 启动时自动读取文档或重建 Collection。

## 7. Dense Retrieval

检索步骤：

1. 使用相同模型与维度生成 Question Embedding。
2. 对 `embedding` 字段执行 COSINE Search。
3. 请求 `content` 与 `source` 输出字段。
4. 返回 Top 3。
5. 丢弃低于 `0.5` 的结果。

返回值只包含 `content`、`source`、`chunk_id` 和 `score`。M8 不进行关键词检索、融合、重排或查询改写。

## 8. Knowledge Agent 与 Graph

Router 增加 `knowledge`：

- “退款单 RF... 现在怎么样” → `refund`
- “退款政策是什么” → `knowledge`

Supervisor Plan 允许 `knowledge`，复杂请求可形成 `order → knowledge`。

Knowledge Agent 不持有业务 Tool：

1. 使用原始用户问题调用 Dense Retrieval。
2. 没有达到阈值的结果时，直接说明知识库没有找到足够依据。
3. 有结果时，将 Top-K Chunk 作为受限 Context 交给 `qwen3.8-27b`。
4. Prompt 要求只根据 Context 回答。
5. 最终文本追加去重后的 source 文件名。

Knowledge Agent 节点内部完成检索和回答，不向 `ChatState` 增加 retrieved_documents 等 RAG 专用字段。复杂路径继续由现有 `agent_results` 收集 Knowledge Agent 最终文本。

## 9. 配置

新增环境变量：

```text
EMBEDDING_MODEL=text-embedding-v4
EMBEDDING_DIMENSIONS=1024
KNOWLEDGE_COLLECTION=ecommerce_knowledge
KNOWLEDGE_TOP_K=3
KNOWLEDGE_MIN_SCORE=0.5
```

Milvus Host/Port、百炼 API Key、Base URL、timeout 和 retry 复用现有配置。`.env.example` 不包含真实 Secret。

## 10. 错误与生命周期

- Embedding 调用复用现有 Provider Error 映射，不暴露 SDK 错误、Key 或 Endpoint。
- Collection 不存在时 Retrieval 返回空结果，由 Knowledge Agent 给出无依据回答。
- 其他 Milvus 异常交由现有 API 500 Contract 处理，不把内部连接信息返回客户端。
- 应用关闭时关闭 Milvus Client；百炼 SDK Client 仍由现有 ChatService 生命周期关闭。

## 11. 测试与验收

默认自动化测试不调用真实百炼：

- Markdown Load 与稳定 Chunk
- Collection Schema、upsert 数据结构
- Dense Search Top-K 与阈值过滤
- knowledge Router 与 Knowledge Agent source 输出
- 无相关知识时不调用 LLM、不编造政策
- 简单 order Route 不受影响
- complex `order → knowledge` 路径

显式真实 Smoke：

- `text-embedding-v4` 返回 1024 维向量
- 4 个 Markdown 文档成功写入 Milvus
- 政策问题检索到合理 Top-K Chunk
- Knowledge Agent 生成带 source 的回答

只运行 M8 相关测试、必要 pytest 回归和少量真实 Embedding/LLM Smoke，不重复无关 Migration、Seed、Swagger 或全部历史真实 Tool 验收。

## 12. 已知限制

- 字符切片不理解 Markdown 语义结构。
- 固定相似度阈值需要通过后续评估校准。
- Dense Retrieval 对 SKU、政策编号等精确关键词可能召回不稳定。
- 没有 Sparse、Hybrid、RRF 或 Reranker；这些属于 M9。
