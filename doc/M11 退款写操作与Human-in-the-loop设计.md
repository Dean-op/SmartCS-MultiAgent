# M11 退款写操作与 Human-in-the-loop 设计

## 1. 目标与边界

M11 首次增加真实业务写入：Refund Agent 理解退款请求并调用一个写 Tool，确定性 Python 逻辑完成资格、金额和风险判断；低风险请求自动完成，高风险请求创建 HumanReview 并通过 LangGraph `interrupt` 暂停，审核 API 使用 `Command(resume=...)` 恢复。

本阶段不增加 Agent、其他业务 Tool、JWT、RBAC、ML 风控、多级审批、外部支付退款、RAG 技术、Redis Memory、Celery、MCP 或 Observability。

## 2. 核心职责

LLM 只负责：

- 识别退款意图。
- 从用户表达中提取订单号、可选请求金额和退款原因。
- 选择退款查询 Tool 或退款申请 Tool。

确定性 Python 逻辑负责：

- ownership。
- 退款资格。
- 合法可退金额。
- 风险等级与自动/人工路径。
- 重复请求保护。
- 审核决定后的数据库状态转换。

Supervisor 和 LLM 不直接写数据库，也不能覆盖规则结果。

## 3. 退款 Tool

Refund Agent 增加一个 Tool：

```text
request_refund(
  order_number: str,
  amount: Decimal | None,
  reason: str
)
```

- `user_id`、`thread_id`、`request_key`、risk 和 decision 不属于 Tool Arguments。
- `thread_id` 来自 LangGraph 可信 config。
- Tool 调用现有 Service 边界，不直接访问 Repository、ORM 或 SQL。
- amount 缺省时由 Service 使用剩余合法可退金额。

## 4. Eligibility

规则按顺序执行：

1. 当前开发用户必须存在且 active。
2. 订单必须存在且属于当前用户。
3. cancelled 订单拒绝。
4. unpaid 或 refunded 支付状态拒绝。
5. 退款期限为 30 天：
   - 已送达订单从 `delivered_at` 计算。
   - 未送达订单从 `paid_at` 计算。
6. 已有退款中，rejected/cancelled 不占用额度；其他状态金额计入已退/处理中金额。
7. 剩余可退金额必须大于 0。
8. 请求金额必须大于 0 且不超过剩余可退金额。

资格拒绝只返回稳定业务 code，不创建 Refund 或 HumanReview。

## 5. Risk

配置：

```text
REFUND_WINDOW_DAYS=30
REFUND_AUTO_APPROVE_MAX_AMOUNT=100.00
REFUND_RECENT_COUNT_DAYS=30
REFUND_RECENT_COUNT_LIMIT=2
```

Low Risk 必须同时满足：

- 请求金额不超过 ¥100。
- 当前用户过去 30 天内非 rejected/cancelled 退款少于 2 次。

Low Risk → AUTO_APPROVE；否则 → MANUAL_REVIEW。

不增加风险标记表、规则 DSL、评分系统或 ML Model。

## 6. 数据模型与 Migration

复用现有 Refund/HumanReview 状态体系，只增加恢复和幂等所需字段：

### refunds

- `request_key VARCHAR(64) NULL`
- Unique Constraint：`request_key`

现有 Seed 为 NULL，不受影响。新退款的 request_key 由服务端对 `thread_id + order_id` 生成 SHA-256 摘要，防止 Graph 重放和同 Thread HTTP 重试重复创建。

### human_reviews

- `thread_id VARCHAR(80) NULL`
- Index：`thread_id`

现有 Seed 为 NULL。新人工退款审核保存 conversation/thread UUID，使 Review API 能恢复对应 Graph。

通过 Alembic 增量 Migration 管理业务 Schema；Checkpoint 表仍由官方 Saver 管理。

## 7. Service 与事务

RefundService 增加两个命令：

### request_refund

在一个数据库事务中：

1. 加载并锁定当前用户订单及退款。
2. 计算 Eligibility 和剩余金额。
3. 查询用户近期退款次数并执行 Risk 规则。
4. 检查 request_key；已存在时返回原结果。
5. Low Risk 创建 completed Refund。
6. Manual Review 创建 pending_review Refund 和 pending HumanReview。

### resolve_review

在一个数据库事务中：

- 只处理 pending Review。
- approve：Review → approved，Refund → completed，设置 reviewed_at/completed_at。
- reject：Review → rejected，Refund → rejected，设置 reviewed_at，不设置 completed_at。
- 重复 approve/reject 返回当前结果，不重复执行退款。

Repository 不 commit；事务由 BusinessTools 的 `session_factory.begin()` 管理。

## 8. Graph 与 interrupt

退款申请路径：

```text
refund_agent
→ request_refund Tool
→ eligibility/risk/write
├→ rejected       → refund_agent → END
├→ auto_completed → refund_agent → END
└→ pending_review → human_review
                     → interrupt(payload)
                     → Command(resume=decision)
                     → resolve_review
                     → END
```

State 只增加：

```text
pending_review = {
  review_id,
  refund_number,
  thread_id
}
```

`human_review` 节点在调用 `interrupt()` 前不执行数据库写入。Manual Refund/HumanReview 已由前一个 Tool 事务幂等创建；恢复时节点从头执行也不会重复创建。

初次中断由 ChatService 转换为正常等待回答。恢复使用相同 thread_id：

```python
Command(resume={"decision": "approve|reject", "note": "..."})
```

参考：<https://docs.langchain.com/oss/python/langgraph/interrupts>。

## 9. Review API

最小开发环境管理接口：

```text
GET  /api/v1/reviews/pending
POST /api/v1/reviews/{review_id}/approve
POST /api/v1/reviews/{review_id}/reject
```

- pending 返回 review_id、refund_number、amount、reason、created_at 和 conversation_id。
- approve/reject Body 只包含可选 note。
- API 先通过 RefundService 读取 pending Review 的 thread_id，再调用 ChatService resume。
- 当前无认证，明确标记为开发接口，不假装具有管理员安全边界。
- 不暴露 request_key、用户 UUID、Checkpoint 内容或内部异常。

## 10. HTTP 结果

Chat API Contract 字段不变：

- 自动完成：assistant 文本说明退款单号、金额和完成状态。
- 不符合资格：assistant 文本说明稳定拒绝原因。
- 人工审核：assistant 文本说明等待审核并包含 review_id/refund_number。

Review API 返回结构化审核结果；approve/reject 的 Graph Resume 最终文本来自确定性结果，不由 LLM 改写审批决定。

## 11. 测试

默认自动化测试覆盖：

- eligible + low risk → completed Refund。
- eligible + high amount/recent count → Refund/HumanReview + interrupt。
- approve → Command resume → Refund completed。
- reject → Command resume → Refund rejected。
- 不存在、ownership、未支付、完全退款、超期、超额。
- request_key 重复保护。
- Review 重复提交保护。
- Graph interrupt payload 和相同 thread resume。
- Review API pending/approve/reject Contract。

显式真实 Smoke 使用专用测试订单或事务准备数据，验证一次自动退款和一次人工审核 approve/reject 路径；不重复 RAG Evaluation、历史 Agent Smoke、Swagger、M0 验收或无关 Migration 往返。

## 12. 已知限制

- completed 仅表示本学习系统中的退款记录完成，不调用真实支付渠道。
- request_key 限制同一 conversation 对同一订单只创建一个退款请求。
- 没有正式管理员认证，Review API 只能用于本地开发。
- 没有退款撤销、部分失败恢复、多级审批、资金对账或通知。
