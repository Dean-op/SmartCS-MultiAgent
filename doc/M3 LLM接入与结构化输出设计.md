# M3 LLM 接入与结构化输出设计

## 1. 文档状态

- 项目：`ecommerce-ai-agent`
- 里程碑：M3——LLM 接入与结构化输出
- 状态：已确认，待实施
- 日期：2026-09-07

## 2. 目标与边界

M3 将 M1 的 Mock Chat 替换为阿里云百炼 `qwen3.7-plus` 真实文本生成，并建立可被后续 Tool Calling、Agent、Router、Supervisor 和 RAG 复用的最小模型访问能力。

本阶段只实现普通文本生成、JSON Schema Structured Output、Provider 错误映射、必要日志、离线自动化测试和显式真实 Smoke Test。不实现 Tool Calling、Agent、LangGraph、正式 Router、Memory、Embedding 或 RAG。

## 3. 方案选择

采用官方 `openai` Python SDK 3.x 的 `AsyncOpenAI` 调用百炼 OpenAI-compatible Chat Completions API。

不直接使用 `httpx` 拼装协议，因为这会重复实现状态码异常、连接生命周期和重试。不提前引入 LangChain，因为 M3 尚不使用 Agent、Tool 或 LangGraph。只增加一个具体 `BailianModel`，不创建单 Provider Interface、Factory、Registry 或 Adapter 层级。

依赖范围：`openai>=3.8,<4`，由 uv 锁定具体版本。

## 4. 模型访问结构

```text
POST /api/v1/chat
        ↓
   ChatService
        ↓
   BailianModel
        ↓
   AsyncOpenAI
        ↓
Alibaba Cloud Model Studio
```

代码组织：

```text
src/ecommerce_ai_agent/
├── llm/
│   ├── client.py
│   ├── errors.py
│   └── schemas.py
└── services/
    └── chat.py

scripts/
└── llm_smoke_test.py
```

不建立 Prompt 目录。M3 只有一个短客服 System Prompt，直接作为 `services/chat.py` 中的模块常量。

## 5. 配置

在现有 `Settings` 中集中增加：

| 环境变量 | 类型 | 默认/约束 |
| --- | --- | --- |
| `DASHSCOPE_API_KEY` | SecretStr，可选 | 调用模型时必填 |
| `BAILIAN_BASE_URL` | HttpUrl，可选 | 调用模型时必填，必须与 Key 地域匹配 |
| `LLM_MODEL` | str，可选 | 调用模型时必填，M3 使用 `qwen3.7-plus` |
| `LLM_TIMEOUT_SECONDS` | float | 默认 30，必须大于 0 |
| `LLM_MAX_RETRIES` | int | 默认 2，范围 0～5 |
| `LLM_TEMPERATURE` | float | 默认 0.2，范围 0～2 |
| `LLM_MAX_COMPLETION_TOKENS` | int | 默认 800，范围 1～8192 |

Key、Base URL 和 Model 不在业务代码中提供隐藏 fallback。`.env.example` 使用空 Key、官方共享 Base URL 示例和 `qwen3.7-plus`；真实专属 Host 只存在于未提交 `.env`。

应用在缺少模型配置时仍可启动，M0 health 和 M2 migration 不依赖模型。只有 Chat 或显式模型调用会返回 `model_not_configured`。

## 6. BailianModel

一个长生命周期 `BailianModel` 包装一个 `AsyncOpenAI` 客户端，提供两个方法：

```text
generate_text(system_prompt, user_prompt) -> str
generate_structured(system_prompt, user_prompt, schema_type[T]) -> T
```

共同请求参数从 Settings 读取：model、temperature、`max_completion_tokens`、timeout 和 max retries。模型客户端在 FastAPI lifespan 结束时关闭。

普通生成检查 `choices[0].message.content` 非空。Structured Output 使用 `response_format.type=json_schema`、`strict=true` 和 Pydantic `model_json_schema()`；返回内容依次经过 `json.loads` 和 Pydantic `model_validate`，最终得到 Typed Python Result。

Structured Output 请求显式关闭 thinking，以降低隐藏推理对严格 JSON 输出的干扰。不传 tools、tool_choice 或 Function Calling Schema。

## 7. Structured Output Schema

定义独立 `MessageAssessment`：

```text
summary: str
requires_business_action: bool
reason: str
```

Schema 使用 `extra="forbid"`，生成 `additionalProperties=false`。它用于判断一条客服消息是否依赖真实账户、订单或退款操作，并给出自然语言摘要和原因。

它不包含 order/refund/knowledge/complex 枚举，不参与 Chat 路由，不实现正式 Router，也不写入 API Contract。

## 8. Chat 升级

M1 请求字段保持不变：

```json
{
  "message": "string",
  "conversation_id": "optional UUID"
}
```

响应字段保持不变，仅将 `mode` 从 `mock` 改为 `llm`，assistant content 来自真实模型。`conversation_id` 仍只用于请求关联，不保存历史、不代表身份。

`ChatService` 接收一个具体 `BailianModel`。FastAPI app state 持有服务实例，`get_chat_service` dependency 只负责读取；测试直接注入带 Fake Model 的 ChatService。

缺少模型配置时 app state 不创建真实客户端，Chat dependency 抛出安全的 `ModelConfigurationError`，其他 API 正常。

## 9. 客服 Prompt

System Prompt 只包含 M3 必要规则：

- 作为简洁、诚实的电商客服回答一般问题。
- 当前没有订单、物流、用户或退款 Tool，不能声称已查询真实业务数据。
- 不能声称已修改订单、数据库或创建退款。
- 请求真实业务操作时，明确说明当前无法执行，并给出可行的一般性指引。
- 不编造订单状态、物流时间或退款结果。

不构建模板引擎、版本系统、Prompt Registry 或动态 Prompt 管理。

## 10. Provider 错误映射

模型层定义一组小型异常，携带公开 `code`、`status_code` 和安全 `public_message`，API handler 复用现有 `ErrorResponse`：

| 场景 | Error Code | HTTP |
| --- | --- | --- |
| Key/Base URL/Model 缺失或模型配置错误 | `model_not_configured` | 503 |
| Provider 鉴权失败 | `provider_authentication_failed` | 502 |
| Rate Limit / quota | `provider_rate_limited` | 503 |
| Timeout | `provider_timeout` | 504 |
| 连接失败/Provider 不可访问 | `provider_unavailable` | 503 |
| Structured JSON/Schema 校验失败 | `structured_output_invalid` | 502 |
| 其他 Provider 4xx/5xx 或空响应 | `provider_error` | 502 |

客户端响应不包含 SDK exception、Provider body、API Key、Authorization Header、专属 Host 或 traceback。服务端日志只记录异常类型，不记录异常字符串。

## 11. Retry 与 Timeout

不实现自定义重试循环。`AsyncOpenAI(max_retries=2)` 使用 SDK 内置短指数退避处理连接错误、408、409、429 和 5xx。timeout 默认 30 秒，可通过环境变量调整。

Provider 已完成重试后才映射为公开错误。Structured Output 解析失败不自动重复请求，避免因模型稳定返回不兼容结构而产生隐性成本。

## 12. Logging

每次模型操作记录一条完成日志，字段仅包括：

- `provider=bailian`
- `model`
- `operation=text|structured`
- `latency_ms`
- `outcome=success|failure`
- 失败时的 `error_type`

不记录 Prompt、Response、Token、Cost、Key、Header 或完整 Provider exception。M3 不引入 OpenTelemetry。

## 13. 自动化测试

默认 pytest 不发出网络请求。使用最小 Fake `AsyncOpenAI` 对象验证：

- 配置读取、范围校验和 Secret repr。
- 缺少 Key/Base URL/Model 时的错误。
- 普通生成请求参数与非空响应。
- Structured Output 请求包含 strict JSON Schema。
- JSON → Pydantic Typed Result。
- 无效 JSON 和 Schema 不匹配。
- Authentication、Rate Limit、Timeout、Connection、Bad Request 和 Provider 异常映射。
- Chat Prompt、安全约束、conversation ID 和 `mode=llm`。
- API Error Contract 与 OpenAPI 502/503/504 Schema。
- M0/M1/M2 全部现有回归测试。

Fake 只替换外部 SDK 网络边界；ChatService、Pydantic Validation、异常映射和 FastAPI handler 使用真实实现。

## 14. 显式真实 Smoke Test

新增：

```text
uv run python scripts/llm_smoke_test.py
```

脚本不被 pytest 收集，也不由普通 smoke 自动调用。它读取本地环境配置并依次验证：

1. Key、Base URL、`qwen3.7-plus` 配置存在。
2. 普通文本生成返回非空内容。
3. JSON Schema Structured Output 返回 `MessageAssessment` typed result。
4. 输出仅包含模型名、文本长度、typed 字段与耗时，不打印 Key、Header、专属 Host 或完整模型内容。

完成直接模型 smoke 后，使用已配置同一 `.env` 的 Docker API 调用 `/api/v1/chat`，验证真实 HTTP Chat 返回 `mode=llm`。

缺少配置时脚本快速失败并提示需要设置的变量名，不打印已有值。

## 15. 普通 Smoke 与 Docker

现有 `scripts/smoke_test.py` 继续验证 M0 readiness、Swagger 和 validation，默认不强制真实模型调用：

- 模型已配置：Chat 必须返回 200 和 `mode=llm`。
- 模型未配置：Chat 允许返回 503 `model_not_configured`，其他 M0/M1 检查必须通过。

Compose 继续通过 `.env` 把模型环境变量传给 API，不新增服务。Docker Engine 未运行时，最终验收前启动 Docker Desktop 并等待六个服务 healthy。

## 16. 不实现

M3 不实现 Tool Calling、Tool Schema、LangChain、LangGraph、Agent、Router、Supervisor、JWT、Authentication、Redis Memory、Conversation Persistence、Embedding、Milvus Collection、RAG、Reranker、退款风控、Human-in-the-loop、Celery、Evaluation、OpenTelemetry 或 Streamlit。

## 17. 完成判定

只有以下条件全部满足才判定 M3 完成：

1. uv 锁定 OpenAI SDK，配置集中且 Secret 未提交。
2. Chat 外部字段保持稳定，真实内容来自 `qwen3.7-plus`，`mode=llm`。
3. Structured Output 完成 JSON Schema → Validation → Typed Result。
4. Provider 错误全部映射到现有 Error Contract，不泄漏敏感信息。
5. 默认 pytest 完全离线，并覆盖模型层、Chat、错误和 M0/M1/M2 回归。
6. 显式真实 Smoke 验证普通生成和 Structured Output。
7. Docker 六服务 healthy，真实 HTTP Chat、health、Swagger 和数据层回归通过。
8. 无 M4+ 实现、无真实 Key、专属 Host 或 `.env` 进入 Git。
9. README、开发记录、测试和脚本进入独立带描述的 M3 Commit。
10. `doc/SmartCS.xmind` 和用户侧 `.gitignore` 修改不被读取、修改、还原或提交。

## 18. 参考依据

- 百炼 OpenAI-compatible API：<https://help.aliyun.com/zh/model-studio/compatibility-of-openai-with-dashscope>
- 百炼地域 Base URL：<https://help.aliyun.com/en/model-studio/base-url>
- 百炼 Structured Output：<https://help.aliyun.com/en/model-studio/qwen-structured-output>
- `qwen3.7-plus`：<https://help.aliyun.com/zh/model-studio/qwen3-7-plus>
- OpenAI Python SDK 错误、重试和 timeout：<https://github.com/openai/openai-python>
