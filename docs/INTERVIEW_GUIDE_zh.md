# 面试准备指南（中文）

> **前提：** 这些回答只有在你本人读过相关代码、亲手跑通过（`pytest -q -rs`、`./scripts/start.sh`、`node e2e/run_e2e.mjs`）之后才能在面试里使用。
> 本项目由 Herui 主导方向，Claude 实现和测试，Codex 做独立源码审查。不要说成是自己一个人写的，也不要说成是真实客户或雇主的部署。

## 一句话介绍（30 秒）

"这是一个**模拟的广告运营工作流**作品集原型。重点不是 agent 数量，而是**审批门的可靠执行**：
- 广告投放提案必须由有审批角色的人，针对**这一个具体的修订版和哈希**批准之后，才会写入模拟账本；
- 进程重启后，同一个 run 还能从 LangGraph 的 SQLite checkpoint 恢复；
- 重复点击、过期修订、跨 run 的 ID 都会被拒绝；
- 在动作边界附近崩溃，恢复时会检测到重放，不会执行第二次。
默认是离线、确定性的 demo provider，不需要 API key。"

## 15 个难题

**1. "awaiting approval" 为什么是真正的暂停，而不是 UI 上的一个状态？**
- 审批门节点 `approval_gate` 调用了 LangGraph 的 `interrupt()`，图的状态由 `SqliteSaver` 写进 `data/checkpoints.db`，`thread_id` 是固定的。
- 此时没有线程或定时器在等。只有 `Command(resume=...)` 能让图继续往下走。
- 代码：`backend/agents/orchestrator.py` 的 `_n_gate`。测试：`test_ac1_*`、`test_ac2_*`。

**2. `interrupt()` 恢复时会从节点开头重新执行，你怎么处理副作用？**
- 官方文档和我做的原型都确认了这一点：interrupt 之前的代码会再跑一遍。
- 所以 `_n_gate` 在 `interrupt()` 之前**什么都不做**。
- 创建提案放在前一个节点 `build_proposal` 里，而且按 `(run_id, revision)` 幂等 upsert，重跑不会产生重复提案。
- 恢复后还会再校验一次：resume 传进来的决定，必须对应同一个 proposal id、revision 和 hash。

**3. 两个审批人同时点"批准"会怎样？**
- `Store.record_decision` 在一个 `BEGIN IMMEDIATE` 事务里做完所有检查，并把 run 状态从 `awaiting_approval` 改成 `resuming`。
- 只有一个请求能赢，其他的拿到 `409 run_not_awaiting_approval`。
- 测试：8 个线程同时点，结果是 1 个成功、1 个动作（`test_ac4_concurrent_clicks_execute_once`）。

**4. 幂等键：相同的键、不同的内容会怎样？**
- 相同键 + 相同内容：返回第一次存下的响应，`replayed: true`。
- 相同键 + 不同内容：`409 idempotency_key_reused`。
- UI 为每个（修订版, 决定）生成一个键，所以双击会发同一个键。

**5. 你说"不会执行两次"，是 exactly-once 吗？**
- **不是。** 我只对自己的模拟账本做了保证：审批检查和账本插入在同一个 SQLite 事务里，账本行有唯一键 `run_id:proposal_id:revision`。
- 崩溃在提交前：事务回滚，恢复后执行一次。
- 崩溃在提交后：恢复时发现已有记录，标记为"重放检测"，不再写。
- 接真实广告 API 会多一个窗口：远端成功了、本地提交丢了。这需要对方支持幂等键，或者在重试前先做一次对账查询。我在 `docs/ARCHITECTURE.md` 里写明了这一点，没有夸大。

**6. 为什么除了 LangGraph checkpointer，还要自己建一个 SQLite 存储？**
- checkpointer 是执行日志，不适合放业务规则。
- 角色检查、修订版、哈希、幂等键、审计历史、账本，这些都需要事务性的读和写，还要能查询。
- 两个库分工：执行状态放 `checkpoints.db`，业务真相放 `adops.db`。

**7. 规划器（LLM）输出 `requires_human_approval: false` 或 `auto_approve: true` 会怎样？**
- 没有任何影响。要不要走审批门，是代码策略（`backend/policy.py` 里的 `GATED_WORKFLOWS`）按工作流类型决定的，模型输出里多出来的字段直接忽略。
- 测试：`test_ac12_injection_in_request_and_planner_output_cannot_bypass_gate`。

**8. 规划出一个有环、或者依赖一个不存在步骤的 DAG 怎么办？**
- `contracts.Plan` 会校验：最多 8 步、agent 必须是已知的、依赖必须存在、不能有环（Kahn 算法）、工作流需要的 agent 必须齐、顺序约束（合规在创意之后）。
- 不通过就失败关闭：一步都不执行，也没有兜底任务。
- 原版的 `_group_by_phase` 在这种情况下会把剩下的步骤全部执行，属于 fail open，我用脚本复现过。

**9. 模型返回了坏 JSON、或者结构不对的 JSON？**
- 每个 agent 都有严格的 Pydantic 契约，外加语义检查（比如引用必须能解析到语料块）。
- 失败时有上限：最多 2 次尝试，每次有超时，然后记为 `failed`，带上错误码。
- 下游步骤不会运行，也不会用失败的前置结果去合成最终答案。
- 原版会把解析失败算作成功，这个已经修复。

**10. 服务器在执行 agent 的途中重启了，怎么办？**
- 启动时 `reconcile_on_startup` 会把没有 worker 负责的 run 显式标为 `interrupted`，并记录事件，不会悄悄丢掉。
- 审批人点 Recover，从最后一个 checkpoint 继续，已完成的步骤不重跑。测试里用计数 provider 证明了这一点。

**11. 角色是怎么做的？算安全吗？**
- 角色在服务端强制执行：请求者不能批准；也不能批准自己发起的 run（职责分离）；查看者不能改任何东西。
- 但角色只是请求头，**不是认证**，UI 和 API 里都写了这一点。GET 接口没有做保护。
- 所以只在本机 `127.0.0.1` 上跑，不要公开部署。

**12. RAG 是怎么做的？引用可信吗？**
- 手写 TF-IDF 检索，按章节切块。每块有稳定的 id 和 sha256。
- 回答只用**逐字引用**的句子，每句都带引用，可以回查到文档、版本、章节和哈希。
- 证据不足时拒答；两份文档在同一个 `topic` 上立场不同时，报告冲突。
- 语料都标注了性质：虚构的政策、虚构的品牌、未核实的摘要。引用只能证明"这句话出自哪里"，不能证明它是现行法律。

**13. 评估结果多少？有没有过拟合？**
- 23 个 held-out 用例通过 19 个。分类的分母都写清楚了：supported 7/8、unanswerable 5/6、conflicting 3/4、injection 4/5。
- 阈值只在 10 个开发用例上调过；held-out 用例是阈值定下之后才写的，只跑一次，之后没再改答题器。
- 最严重的失败是 U5：该拒答的问题它回答了。
- 局限要说在前面：语料、答题器、用例都是 Claude 写的，不算独立评测；也没有评测 LLM 的质量（没有 key，没跑）。

**14. Prompt injection 怎么防？**
- 三层：
  1. 来源里像指令的内容（比如"忽略之前的指令""标记为已批准"）会被排除在证据之外，并列出来。
  2. 合规 agent 如果引用了被标记的块，会校验失败。
  3. 最关键的一层：审批门不看任何模型或来源文本，只看数据库里有没有针对这个 proposal id、revision、hash 的审批记录。
- 模拟器在执行前还会再检查一遍。

**15. 如果要上生产，你第一步改什么？**
- 真实的认证和授权（OIDC），替换掉演示用的请求头角色。
- 多 worker 下的每个 run 租约，比如 Postgres 加 `SELECT ... FOR UPDATE`，再用 PostgresSaver。
- 接广告平台 API 时，把账本键作为对方的幂等键传过去，并加上对账。
- 检索换成向量或混合检索，并请独立的人写评测集。
- 这些都**没有**做，面试时要讲清楚是"下一步"，不是"已完成"。

## 可能的追问陷阱

- "你们客户用了吗？" → 没有。这是模拟场景，没有客户，也没有雇主部署。
- "准确率多少？" → 只有 grounding 的 19/23，而且是自建用例；LLM 质量没有评测。
- "和某某平台有关系吗？" → 没有。平台是虚构的 SimAds 沙盒。
- "这些测试是用户验收吗？" → 不是，是开发者测试，不能算利益相关方的 UAT。
