# Laya 决策接口 · 语义说明（给调用方）

面向"要用这个服务做判断"的开发者。看完这篇不用看 schema 也能接。

## 一句话心智模型

> 你把**情境**和**要判断的问题**交出去，它回你**结论 + 把握程度**。
> 它不生成文字、不解释理由、不替你拍阈值。

## 一、三种提问方式 = 三类业务问题

| 语义 | 一句话 | 典型业务 | 问法 |
|---|---|---|---|
| **选择类** | 这属于哪一类 / 该给谁 | 工单分派、内容分类、模型路由、打标签 | `choose(情境, 问题, 选项)` / `type=choice` |
| **程度类** | 有多严重 / 打几分 | 优先级、紧急度、风险分级、满意度打分 | `rate(情境, 问题, 档位)` / `type=score` |
| **是非类** | 要不要 / 是不是 | 是否转人工、是否放行、是否违规、是否需要审批 | `yes_no(情境, 问题)` / `type=noul` |

选哪个的标准很简单：**答案是"多选一"用选择类，"程度/数值"用程度类，"是/否"用是非类。**
多分类不要用是非类；数值区间（如 0–100 分）请用带档位的程度类。

## 二、入参：你只需要给三样东西

### 1. 情境 state（必填）
- 可以是**纯文本**、**JSON 对象**（如 `{"subject": "...", "body": "..."}`）、或**消息数组**（`[{"role","content"}, …]`）
- 长度建议：英文 < 500 token，中文等多语 < 1000 token（模型序列硬上限 512 token）
- 超长默认**截断并回 warning `state_truncated`**；想让它报错就把 `truncate_state: false`
- 写法建议：把"人看到的关键信息"放进去（标题、正文、来源、金额…），不要塞整篇文档

### 2. 问题 questions（与 preset 二选一）
```jsonc
{
  "department": {                       // 问题名（你自己起，会和答案一一对应）
    "type": "choice",                   // choice | score | noul
    "instructions": "该由哪个团队处理？",  // 用自然语言写清"判断什么"
    "criteria": {                       // 选项：{"标签": "说明"}，或 ["标签1","标签2"]
      "billing":   "退款、对账、计费争议",
      "technical": "故障、缺陷、访问异常"
    }
  }
}
```
- **选择类**：`criteria` 必填，标签唯一；给出「标签: 说明」比只给标签准得多
- **程度类**：`criteria` 是**从低到高**的档位数组，如 `["低","中","高"]`
- **是非类**：`criteria` 可省
- 一次可以问多个问题（同一次计算完成，几乎不加耗时），但每个问题要独立、别互相依赖

也可以直接用内置问题集：`preset` = `triage`（工单）/ `router`（小模型 vs 大模型路由）/ `guard`（越狱/注入）/ `moderation`（内容安全）/ `email`（邮件分类）。

### 3. 策略 policy（可选，都有默认值）
| 字段 | 语义 | 默认 |
|---|---|---|
| `model` | 用哪套权重：`multilingual`（中文/多语）/ `english` / `typed-decisions` | multilingual |
| `timeout_ms` | 超时（超过就返回 504，不会无限等） | 5000 |
| `max_state_chars` | 情境截断长度 | 4000 |
| `truncate_state` | 超长是截断(true)还是报错(false) | true |
| `max_options` | 单问选项数上限（保护 token 预算） | 20 |

## 三、最小可用示例

**HTTP（任何语言都能用）**
```bash
curl -s http://127.0.0.1:8765/v1/decide -H 'content-type: application/json' -d '{
  "state": {"body": "账单重复扣款，请退款"},
  "questions": {"department": {"type": "choice", "instructions": "该由哪个团队处理？",
                               "criteria": {"billing": "退款/计费", "technical": "故障/缺陷"}}}
}'
```

**Python 语义层（推荐给业务代码）**
```python
from laya_api.client import LayaClient

c = LayaClient("http://127.0.0.1:8765")

# 选择类
d = c.choose({"body": "账单重复扣款，请退款"}, "该由哪个团队处理？",
             {"billing": "退款/计费", "technical": "故障/缺陷"}, tau=0.6)
print(d.label, d.confidence, d.auto, d.distribution)
# → billing 0.9863 True {'billing': 0.9988, 'technical': 0.0012}

# 程度类
u = c.rate({"body": "系统登录失败，全组都无法使用"}, "紧急程度", ["低", "中", "高"], tau=0.6)
print(u.level, u.score, u.needs_review)

# 是非类
h = c.yes_no({"body": "账单重复扣款，请退款"}, "需要人工介入吗？", tau=0.6)
print(h.answer, h.probability)   # → False 0.031
```

## 四、返参：结论 + 把握程度

| 字段 | 语义 | 怎么用 |
|---|---|---|
| `choice` | 选择类的结论（选中的标签） | 直接当分类结果 |
| `score` + `legend` | 程度类的期望分 + 档位名 | `score` 是期望值（可小数）；取整/就近就是档位，也可按业务自定义区间映射 |
| `noul` | 是非类 P(是)（0~1） | ≥0.5 视为"是"；接近 0.5 说明模型也不确定 |
| `confidence` | **模型对这次判断的把握**（0~1，已校准） | 决定"能不能自动处理"的门槛 |
| `probabilities` | 完整概率分布 | 做阈值路由、做"次优候选"兜底、做人工复核排序 |
| `action.act_probability` | 模型"是否给出明确动作"的分支概率 | 健康指标，一般不用 |
| `usage.latency_ms` / `queue_wait_ms` | 推理耗时 / 排队耗时 | 性能监控 |
| `usage.input_tokens` | 本次消耗的上下文长度 | **本地模型不计费**，仅容量参考 |
| `usage.cold_start` | 是否走了冷启动（首次加载） | 告警排噪用 |
| `warnings` | 如 `state_truncated` | 出现就说明情境被裁剪了 |
| `engine` | 当前形态（`laya_mlx` / `laya_torch`）+ 版本 | 排障对账 |
| `request_id` | 你传什么回什么 | 建议带上，做日志追踪 |

**没有 `output_tokens`/文本字段**：这个模型不做生成，只做判断。

## 五、三条使用规则（重要）

1. **概率必看，阈值你定。** `confidence` 是模型自校准值，**不等于准确率**。做法：抽 100–200 条已有标准答案的历史数据跑一遍，选一个"自动处理准确率可接受、转人工比例可承受"的 τ（常见起点 0.6，再按业务调）。
2. **"不确定"不是错误。** 低 `confidence` 是正常输出，用它做分支：`auto=True` 自动处理，`auto=False` 转人工或交给大模型。
3. **选项文案就是业务口径。** `criteria` 说明写得含糊，判断就会漂；改业务口径时优先改这里。

## 六、常见误用

| 误用 | 后果 | 正解 |
|---|---|---|
| 把 `confidence` 当准确率直接对外承诺 | 埋雷 | 用自己样本标定 τ |
| 一次问十件事、问题互相依赖 | 结果难解释 | 拆成多个 qid（同次计算，成本极低） |
| 状态塞整篇文档 | 超长截断、判断漂 | 先摘要关键字段再传 |
| 只取 `choice` 不看分布 | 无法做阈值路由 | 用 `probabilities` + τ |
| 用是非类表达多分类 | 语义错 | 用选择类 |

## 七、联调抓手

- **测试台**：`http://127.0.0.1:8765/`（或 `/ui`）— 手填情境与问题、选内置 preset、看概率条与 τ 判定
- **契约样例**：`contract/examples/*.json` 可直接回放；完整字段见 `contract/decision.v1.schema.json`
- **内置问题集列表**：`GET /v1/presets`
- **错误码**：`SCHEMA_INVALID` 400（字段/选项不合法）、`OVER_BUDGET` 413（超 token 预算）、`BUSY` 503（队列满）、`MODEL_UNAVAILABLE` 503（后端不可用）、`TIMEOUT` 504
