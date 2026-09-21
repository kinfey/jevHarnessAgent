# Jev Harness Agent：Coding Agent 控制平面与麦当劳点餐演示

[English](README.md) | **简体中文**

![arch](./arch/arch.png)

本项目比较两种 Agent Harness：

- **传统 Harness**：GitHub Copilot Python SDK 配合 `gpt-6-astra` 理解需求、选择工具，并通过 Agent loop 调用麦当劳中国 MCP。
- **Jev Harness**：TypeSafe Jev 先生成带置信度的类型化决策；本地 Python 代码执行检查、缩小工具范围，再将 MCP 执行交给同一个 `gpt-6-astra` 模型。

CLI 默认请求使用中文，内容为：

> 我要一份板烧鸡腿堡套餐，中杯可乐，到店取餐。先试算，不要真正下单。

Dashboard 仅使用浅色主题，支持英语、简体中文和繁体中文，通过左右实时控制台并行对比两条执行路径。

## 架构

### 系统全貌：两条并行的 Harness

所有架构图均使用 Markdown `text` 代码块，不需要 Mermaid 或图表插件。图中保留英文技术标识，便于对照代码。

```text
                  +-----------------------------------------+
                  | Browser Dashboard                       |
                  | Light UI / English / zh-CN / zh-TW       |
                  | Jev console | Traditional console       |
                  +--------------------+--------------------+
                                       |
                             POST /api/compare-stream
                                       |
                  +--------------------v--------------------+
                  | Local Python HTTP Server                |
                  | web.py / asyncio tasks + event queue    |
                  | Same request / commit=False             |
                  +----------+-------------------+----------+
                             |                   |
               +-------------+                   +-------------+
               |                                               |
  +------------v------------------+          +------------------v------------+
  | JEV HARNESS                   |          | TRADITIONAL HARNESS           |
  | run_jev()                     |          | run_traditional()             |
  +-------------------------------+          +-------------------------------+
  | Concurrent startup:           |          | Raw request                   |
  | TypeSafe SDK -> remote Jev API |          | + ordering instructions       |
  | Copilot runtime (empty mode)  |          | + broader MCP tool set        |
  +-------------------------------+          +-------------------------------+
  | Six Choice answers            |          | Copilot Python SDK            |
  | -> typed plan + confidence    |          | mode="copilot-cli"            |
  +-------------------------------+          | Default runtime context       |
  | Local Python gate             |          +-------------------------------+
  | - confidence / required data  |          | GPT-6-astra agent loop        |
  | - commit / intent check       |          | Interpret -> choose tool      |
  | Review needed -> STOP         |          | -> read result -> repeat      |
  | Pass -> plan + allowed tools  |          +----------------+--------------+
  +-------------------------------+                           |
  | Copilot Python SDK            |                           |
  | Explicit MCP ToolSet          |                           |
  | No skills / config discovery  |                           |
  +-------------------------------+                           |
  | GPT-6-astra agent loop        |                           |
  | Typed plan + location context |                           |
  | + workflow prompt             |                           |
  +---------------+---------------+                           |
                  |                                           |
                  +--------------------+----------------------+
                                       |
                            Streamable HTTP (MCP)
                                       |
                  +--------------------v--------------------+
                  | McDonald's China MCP                    |
                  | https://mcp.mcd.cn                       |
                  | Stores / menu / details / coupons       |
                  | calculate-price                         |
                  +-----------------------------------------+
```

两条路径分别通过 **GitHub Copilot Python SDK → JSON-RPC → Copilot runtime → GPT-6-astra** 执行工具循环。共用 MCP 节点表示访问同一个远程服务，而非共用 Agent session。Jev 是额外的远程决策 API，并不替代 GPT-6-astra。

### 实时回传：不等待两条路径全部完成

```text
  Jev decisions / gate events       Traditional context / phase events
               |                                  |
  Copilot model / tool / usage       Copilot model / tool / usage
               |                                  |
               +----------------+-----------------+
                                |
                         Progress callbacks
                                |
                     asyncio.Queue (web.py)
                                |
                 HTTP/1.1 chunked NDJSON + flush
                                |
                   Browser fetch ReadableStream
                                |
                      Dispatch by engine name
                                |
                 +--------------+--------------+
                 |                             |
      +----------v-----------+      +----------v-----------+
      | LEFT: Jev            |      | RIGHT: Traditional   |
      | Live event log       |      | Live event log       |
      | Decisions JSON       |      | Agent context        |
      | Tokens / quote       |      | Tokens / quote       |
      +----------------------+      +----------------------+
```

控制台逐行追加收到的进度事件，各自完成后显示完整结果区。这些内容是执行事件和应用提供的上下文，不是模型隐藏的思考过程。

### 组件与代码对照

| 组件 | 运行位置／接口 | 对应文件 |
|---|---|---|
| 双栏 Dashboard | 浏览器；接收 NDJSON 流 | `src/harness_agent/web/index.html` |
| HTTP 服务与并行协调 | 本地 Python；默认 `127.0.0.1:8765` | `src/harness_agent/web.py` |
| Jev 决策层 | TypeSafe Python SDK 调用远程 Jev API | `src/harness_agent/jev.py` |
| Python gate 与工具白名单 | 本地 Python 逻辑，非独立 API 或 CLI | `src/harness_agent/copilot_runner.py` |
| 两条 Copilot 执行路径 | SDK 控制 runtime，使用 `gpt-6-astra` | `src/harness_agent/copilot_runner.py` |
| 计划与指标数据 | `OrderPlan`、`RunMetrics` | `src/harness_agent/models.py` |
| 本地配置 | 从 `.env` 读取凭证与模型设置 | `src/harness_agent/config.py` |
| CLI 入口 | `simulate`、`run`、`benchmark` | `src/harness_agent/cli.py` |

后端使用 `.env` 中的 `TYPESAFE_API_KEY` 和 `YOUR_MCP_TOKEN`，不要将它们写入前端代码。Dashboard 固定使用 `commit=False`，不暴露 `create-order`。CLI 的显式提交功能与该预览路径分开。

### 延伸到 coding agent

以下是可扩展的架构方向，并非已经实现的完整 coding agent：

```text
  Coding request
       |
       v
  Jev: bounded task / risk / tool-family judgments
       |
       v
  Python policy: permissions / paths / budgets / review gates
       |
       v
  GPT-6-astra: inspect code / propose edits / investigate failures
       |
       v
  Tools: scoped file access / edits / test execution
       |
       v
  Deterministic checks: tests / lint / diff / approval
       |
       +--> Pass: return result
       +--> Fail: bounded retry or human review
```

| 层 | 建议的 coding agent 职责 |
|---|---|
| Jev / System One | 判断任务类型、变更风险、所需工具类别与人工审核需求 |
| 代码控制平面 | 执行置信度门槛、权限、预算、迭代上限、允许路径及副作用检查 |
| GPT-6-astra | 生成文字和代码、跨文件推理、调查故障 |
| MCP / 本地工具 | 在授权范围内读取、编辑、测试及查询服务 |
| 验证器 | 检查 schema、diff、测试、lint 和敏感信息；将结果交回代码控制的策略 |

Jev 不是代码生成器，也不是自主运行的 Agent loop。当前项目由 Python 执行前置检查与工具过滤，后续调用及参数仍由 GPT-6-astra 选择。完整状态机、代码验证和受限重试属于扩展方向，而非已有能力。

## 点餐执行流程

```text
  User request: grilled chicken combo / Coke / pickup / quote only
       |
       v
  Jev: one request, six Choice questions evaluated in parallel
       |
       +--> fulfillment / meal / size / drink / quantity / action
       +--> confidence / probabilities
       |
       v
  Python gate
       |
       +--> Missing required information or low confidence: STOP
       |
       +--> Pass: OrderPlan + location context + allowed tools
                    |
                    v
            Copilot GPT-6-astra
                    |
                    v
            query-nearby-stores
                    |
             +------+-------------------+
             |                          |
             v                          v
         query-meals            query-store-coupons
             |                          |
             v                          |
         query-meal-detail              |
             |                          |
             +-------------+------------+
                           |
                           v
                     calculate-price
                           |
                           v
                Quote + usage + event metrics
                           |
                           v
                 Dashboard / CLI output

  Dashboard preview: create-order is NOT exposed.
```

图中表示自取场景的数据依赖，而非代码强制执行的固定顺序。确定门店后，菜单和优惠查询可以独立进行；实际是否并行取决于 Agent 的工具调用。

Jev 在一次请求中评估六个字段。若最低置信度低于 `JEV_CONFIDENCE_THRESHOLD`，或缺少取餐方式、主餐、饮料信息，流程会在调用 MCP 前停止。价格计算由 MCP／代码负责，不交给 Jev。

Jev 路径将分类与隔离的 Copilot SDK `empty` runtime 启动并行执行。它关闭 session store、skills、配置发现和自定义指令，仅显式允许所选 MCP 工具。大型菜单结果保持 inline，避免重新引入文件读取工具，但大型响应也会增加上下文大小。

## 与传统 Harness 的比较

| 维度 | 传统：Copilot + GPT-6-astra | Jev + Python + Copilot |
|---|---|---|
| 控制流 | 模型在 Agent loop 中选择下一步 | Python 先执行检查与工具过滤，后续仍由模型执行工作流提示 |
| 意图和参数 | 生成式模型理解请求 | Jev 在一次并行请求中生成封闭集合决策 |
| 工具范围 | 预览模式暴露较宽的只读点餐工具集 | 根据计划缩小范围；自取不暴露外送地址工具 |
| 不确定性 | 本演示没有单独的类型化置信度阶段 | Choice 分布与 confidence 支持门槛检查 |
| 类型安全 | 工具参数仍需运行时验证 | Jev 决策使用声明的选项；MCP 参数仍需验证 |
| 生成能力 | 适合文字、代码与复杂问题调查 | Jev 不生成自然语言回答，GPT-6-astra 仍负责生成与执行 |
| 延迟 | 多轮模型与工具调用 | 增加分类阶段，但缩小后续运行环境与工作流范围 |
| 执行边界 | 取决于 runtime 权限与工具配置 | 增加本地检查与显式 MCP ToolSet 来约束执行 |

**不能将 TypeSafe 发布的 193.6×／444.6× 数字直接套用到本演示。** 这些数字来自其特定工作流评测，并非本应用的端到端表现。CLI `benchmark` 按顺序运行两种 Harness；Dashboard 则并行运行。单次执行或页面竞速都不足以得出统计可靠的加速结论。

Jev 不保证整个流程一定更快。Runtime、上下文、回答长度、网络状态与 MCP 延迟都会影响结果。许多运行时优化也可以用于传统路径。

## 安装与使用

需要 Python 3.11+，使用 Microsoft package feed proxy 安装：

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install \
  --index-url https://packagefeedproxy.microsoft.io/pypi/simple \
  -e ".[dev]"
python -m copilot download-runtime
```

创建示例时，代理源提供 `typesafe-sdk 0.5.7`，因此项目采用官方 cookbook 支持的最低版本 `>=0.5.7`。如果代理源已有兼容的新版本，pip 可以选择新版。在线执行还需要有效的 GitHub Copilot 身份认证及 `gpt-6-astra` 模型访问权限。

将本地 `.env` 中的占位符替换为自己的值：

```dotenv
YOUR_MCP_TOKEN=YOUR_MCP_TOKEN
TYPESAFE_API_KEY=YOUR_TYPESAFE_API_KEY
MCD_MCP_URL=https://mcp.mcd.cn
COPILOT_MODEL=gpt-6-astra
TYPESAFE_MODEL=jev-latest
JEV_CONFIDENCE_THRESHOLD=0.75
```

从麦当劳中国 MCP 控制台获取 `YOUR_MCP_TOKEN`。程序通过 HTTP Authorization 请求头使用 Bearer 认证发送该令牌。`.env` 已被 `.gitignore` 排除。

运行完全离线、无副作用的流程示意：

```bash
harness-agent simulate
```

连接真实 MCP 服务，仅查询和试算：

```bash
harness-agent run --engine traditional
harness-agent run --engine jev
harness-agent benchmark
```

启动支持并行执行的本地 Dashboard：

```bash
harness-dashboard
```

浏览器打开 `http://127.0.0.1:8765`。页面不提供提交订单的入口；查找自取门店时，请按需提供位置。

在线运行的结果 JSON 包含：

- `steps`：Harness 工作流摘要，不是按时间排列的实际工具调用记录。
- `jev_decisions`：Choice 答案、置信度、概率分布、检查结果和类型化计划。
- `agent_context`：应用提供的 prompt、模型及 MCP 白名单，不含凭证字段；并非 runtime 的全部内部上下文。
- `token_usage`：Jev 与每轮 Copilot 的 input/output/cache 用量、合计和 SDK 回报的 cost。
- `event_types`：SDK session/model/tool 事件计数。

显式传入 `--commit` 会启用提交能力，**可能创建真实订单**。Dashboard 和 benchmark 不需要此选项：

```bash
harness-agent run --engine jev \
  --request "我要一份板烧鸡腿堡套餐，中杯可乐，到店取餐，确认创建订单。" \
  --commit
```

## 评测设计

保存每次 JSON 输出并比较：

1. **正确性**：餐点、规格、饮料、数量、取餐方式、优惠适用性及最终报价。
2. **效率**：端到端 p50/p95、模型阶段数、可观测的模型调用／usage 事件及工具执行次数。`model_stages` 表示架构阶段，不是实际模型请求数。
3. **可靠性**：人工审核检查结果、无效参数、重试和未授权副作用。
4. **成本**：已回报的 token 用量、缓存行为和实际服务商账单，而非仅比较耗时。

`tool_events` 当前统计 `TOOL_EXECUTION_START` 事件，不是流式 delta 数量；没有识别具体工具前，也不应将其全部当作 MCP 请求。

Input tokens 按模型回合累计，包含重复上下文和缓存相关用量。未核实计费语义前，不要把 SDK 的 `cost` 当作货币金额。解读合计前，应检查各用量字段是否实际回报。

严谨评测应固定任务和成功标准，进行预热、多次运行、交替执行顺序，并仅比较完成报价的结果。若要分离 Jev 本身的收益，应加入同等优化但不使用 Jev 的对照组。

## 参考资料

- [TypeSafe：Introducing System One Models & Jev](https://typesafe.ai/blog/introducing-system-one-models-and-jev)
- [TypeSafe Python SDK 快速入门](https://docs.typesafe.ai/introduction/quickstart)
- [TypeSafe：How to build with System One](https://docs.typesafe.ai/concepts/how-to-build-with-system-one)
- [TypeSafe：Jev 1.13 已知局限](https://docs.typesafe.ai/model-jaggedness/jev-1.13)
- [GitHub Copilot Python SDK](https://github.com/github/copilot-sdk/tree/main/python)
- [麦当劳中国 MCP Server](https://github.com/M-China/mcd-mcp-server)
- 项目故事：[English](blog/blog.en.md) | [简体中文](blogs/blog.zh.md)
