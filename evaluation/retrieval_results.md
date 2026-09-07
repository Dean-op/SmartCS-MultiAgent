# M9 Retrieval Evaluation Result

运行环境：8 个 Markdown、24 个 Chunk、12 条查询、`text-embedding-v4`、Milvus BM25/RRF、`qwen3-rerank`。

| Pipeline | Hit@1 | Hit@3 |
| --- | ---: | ---: |
| Dense Only | 1.00 | 1.00 |
| Dense + BM25 + RRF | 1.00 | 1.00 |
| Dense + BM25 + RRF + Reranker | 1.00 | 1.00 |

## 代表性排名变化

### 七天无理由退货

- Dense：refund → refund → after-sales
- Hybrid：refund → refund → refund
- Rerank：refund → membership → after-sales

Hybrid 把同一退款文档的三个相关章节聚合到 Top 3；Reranker 保持正确 Top 1，但降低了后续候选的主题集中度。

### 预售商品 48 小时发货

- Dense：preorder → preorder → shipping
- Hybrid：preorder → preorder → preorder
- Rerank：preorder → shipping → preorder

BM25 对“预售”和“48 小时”精确词有明显作用；三种方法的正确 Chunk 都位于 Top 1，因此 Hit 指标没有变化。

### 优惠券订单退款返券

- Dense：coupon → refund → invoice
- Hybrid：coupon → refund → coupon
- Rerank：coupon → membership → invoice

三种方法都保留正确 Top 1。Hybrid 改善了 Top 3 中的同主题召回，Reranker 在这个小候选集上反而引入了较弱结果。

## 结论

当前评估集较小且政策主题区分仍然清晰，Dense 已达到满分，所以无法从 Hit@1/Hit@3 观察到 Hybrid 或 Reranker 的数值提升。Hybrid 对精确词和 Top-3 主题集中度有局部改善；`qwen3-rerank` 没有提高命中指标，并在部分查询中降低了非首位候选质量。

该结果说明“增加检索阶段”不等于自动改善质量。后续若需要判断真实收益，应扩大并提高评估集难度，而不是继续调参追求当前小集合上的表面提升。
