# TEMU 全托管卖家 Agent（第一阶段 MVP）

面向 TEMU 全托管卖家的本地 Web MVP：**趋势选品（AI 建议 + 人工审批）+ 简单客服回复草稿 + 合规硬过滤 + 审计后台**。
无 TEMU 店铺授权也能用演示数据 / CSV 导入完整运行。

## 快速开始

### 方式 A：本地直接运行（无需 Docker）

```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

打开 http://127.0.0.1:8000 即进入中文管理后台。首次启动自动导入演示数据（20+ 商品信号、含应被拦截的违禁品示例）。

### 方式 B：Docker Compose（PostgreSQL + Redis）

```bash
cp .env.example .env   # 按需修改
docker compose up --build
```

启动后访问 http://localhost:8000。

### 演示步骤

1. **数据总览**：查看信号 / 候选 / 会话统计。
2. **今日趋势**：点「▶ 运行选品分析」，系统对全部信号做聚类、合规硬过滤、评分。
3. **候选商品**：查看排行榜；`TOP/CONSIDER` 可「批准」，`REJECT`（儿童玩具、带电池、液体、侵权等）无法批准。点标题进入详情，可看到每个分项的计算依据。
4. **合规检查**：对任意商品重新执行规则检查，查看命中规则。
5. **客服工作台**：输入买家问题（如「这个发夹什么颜色」「我要退款」），系统生成带置信度和引用来源的回复草稿；高风险问题强制转人工；回复需人工确认后才可发送。
6. **规则配置**：调整评分权重（和必须为 1）、目标市场、自动化等级（默认 L1）、L2 自动回复总开关。
7. **操作审计**：所有导入、选品、审批、发送、配置变更均有记录。

### CSV 导入格式

见 `backend/data/sample_products.csv`，表头：
`external_id,title,category,price,sales_30d,growth_7d,review_count,weight_g,cost,size,material`
在「今日趋势」页点「导入 CSV」上传即可，随后运行选品分析。

## 系统架构

```
数据来源层   TEMU公开页面/公开趋势/搜索趋势/节日日历/CSV/供应商报价/官方API（后续）
数据接入层   定时调度(Celery预留) / CSV导入器 / TEMU适配器 / 清洗标准化 / 聚类去重 / 重试限流
数据存储层   PostgreSQL(pgvector预留) / Redis / SQLite(本地模式) / 对象存储(预留)
智能工作流   选品Agent / 合规Agent / 客服Agent —— 确定性编排；数值与风险判断全部由程序规则完成
应用层       中文运营后台（数据总览/趋势/候选/合规/客服/知识库/数据源/规则配置/审计）
```

三个专职 Agent 的职责边界：

- **选品 Agent**：热度变化、季节性、竞争度、利润与物流估算、评分排行、可解释理由。评分公式：需求热度30% + 增长速度20% + 竞争空间15% + 预计利润15% + 物流友好度10% + 非季节稳定性10%（后台可调）。**大模型不参与任何打分。**
- **合规 Agent**：选品前置门槛。14 类硬性禁售规则（儿童用品、玩具、食品保健品、化妆品、医疗功效、带电池/插电/无线、液体粉末喷雾、刀具、安全防护、承重件、食品接触、高风险宠物用品、疑似侵权等）命中即 REJECT；缺重量/尺寸/材料/供应信息为 REVIEW；只允许 PASS / REVIEW / REJECT 三种结果，全部保存命中规则与解释。目标市场可配置。PASS 仅表示"未发现特定品类的复杂准入要求"，最终需人工确认。
- **客服 Agent**：识别语言→意图→查知识与订单→生成回复→风险检查→分级处理。退款赔偿、客诉升级、人身安全、法律、地址改、无答案、低置信度、要求人工一律转人工。回复标注引用来源，不编造订单/物流信息。自动化等级 L0/L1（默认）/L2/L3，L3 高风险永不自动。

## 关键 API

`POST /api/imports/products`、`POST /api/imports/csv`、`GET /api/signals`、`POST /api/selection/run`、
`GET /api/candidates`、`GET /api/candidates/{id}`、`POST /api/candidates/{id}/compliance-check`、`POST /api/candidates/{id}/approve`、
`GET|POST /api/conversations`、`POST /api/conversations/{id}/generate-reply`、`POST /api/replies/{id}/approve`、`POST /api/replies/{id}/send`、
`GET|POST /api/knowledge`、`GET /api/audit-events`、`GET|POST /api/settings`、`GET /api/settings/integrations`、`POST /api/settings/integrations/temu`

交互式文档：http://127.0.0.1:8000/docs

## 目录结构

```
temu-agent/
├── docker-compose.yml            # PostgreSQL + Redis + 后端
├── .env.example                  # 示例环境变量（密钥只放 .env）
└── backend/
    ├── app/
    │   ├── main.py               # FastAPI 入口 + 后台页
    │   ├── config.py             # 全部配置来自环境变量
    │   ├── db.py / models.py     # SQLAlchemy 模型
    │   ├── schemas.py            # Pydantic 校验
    │   ├── appsettings.py        # 权重/市场/自动化等级设置 + 审计
    │   ├── seed.py               # 演示数据（含违禁品示例）
    │   ├── adapters/temu.py      # TemuAdapter / MockTemuAdapter / OfficialTemuAdapter
    │   ├── services/
    │   │   ├── importer.py       # 信号导入、CSV、清洗、聚类去重
    │   │   ├── compliance.py     # 合规硬过滤规则
    │   │   ├── scoring.py        # 评分（可追溯 score_detail）
    │   │   ├── selection.py      # 选品编排
    │   │   ├── customer_service.py # 客服工作流
    │   │   └── llm.py            # LLMProvider（规则实现 + OpenAI 兼容，自动降级）
    │   └── routers/api.py        # 全部 API
    ├── alembic/                  # 数据库迁移
    ├── templates/admin.html      # 中文管理后台
    ├── data/sample_products.csv  # 示例导入文件
    └── tests/                    # pytest（合规/评分/客服/API链路/适配器）
```

## 核心数据模型

`ProductSignal`（原始热度快照）、`ProductCandidate`（候选+评分+score_detail）、`ComplianceCheck`（合规记录）、
`CustomerConversation` / `ReplyDraft`（客服会话与回复草稿）、`KnowledgeDocument`（知识库）、
`AuditEvent`（操作审计）、`AppSetting`（可配置规则）、`IntegrationSetting`（接入配置，密钥加密存储）、`TrendSnapshot`（趋势历史）。

## 需求理解中的关键假设与默认值

1. **前端**：第一阶段采用后端渲染的中文单页后台（Tailwind CDN），Next.js 前端放到后续阶段 —— 目标是让 MVP 在无 Node 构建环境下也可运行，API 已按前后端分离设计。
2. **数据库**：本地默认 SQLite（零依赖），Docker Compose 下用 PostgreSQL；pgvector 语义检索在第二阶段接入（当前知识库用关键词匹配）。
3. **利润估算**：售价×0.75 供货系数减采购成本（全托管粗略模型），可在 `services/scoring.py` 调整。
4. **演示订单**：客服演示用订单号 `20240901123`（运输中）、`20240901456`（已签收）。
5. **"同款去重"**：按归一化标题+类目聚类；跨语言同款识别（如中英文标题）留待第二阶段 embedding 方案。
6. **密钥存储**：MVP 中 TEMU 密钥经混淆后入库且任何接口/日志不回显；生产建议 KMS 或 fernet。

## 测试

```bash
cd backend
pip install pytest httpx
pytest -v
```

覆盖：合规硬过滤、评分可追溯、聚类去重、客服转人工规则、CSV→选品→审批全链路、设置校验、适配器能力声明。

## 暂未接入的 TEMU 官方功能（如实声明，不以模拟冒充真实）

以下能力当前**均未接入 TEMU 官方 Open API**（无授权凭证）：

- 官方 OAuth 授权与 Token 刷新（`authorize` / `refresh_token` 仅有骨架，未对接真实端点）
- 商品列表/详情同步（`list_products` / `get_product`）
- 订单查询（`list_orders` / `get_order`）
- 库存查询（`get_inventory`）
- 物流轨迹查询（`get_logistics`）
- 站内信拉取与自动发送（`list_messages` / `send_message`）

替代方式（在界面中已明确显示）：商品信号用演示数据/CSV 导入；订单状态用演示数据；买家回复用**人工复制模式**（在卖家后台手工粘贴）。`OfficialTemuAdapter` 已实现带超时/重试/限流的请求通道，取得 TEMU Partner Platform 授权后只需在后台切换为 official 并填写密钥。系统不会调用私有接口或绕过任何验证。

## 评分可信度层（2026-10 新增）

评分本身不难，难的是说清**哪些数字有依据、哪些是我拍的**。这一层就是为这件事加的。

| 模块 | 干什么 | 关键设计 |
|---|---|---|
| `services/gate.py` | 第 0 关硬门槛：超重、负毛利、价格无空间、缺强制认证 | 门槛在评分**之前**，高分不能买通资格；每个阈值带 `confirmed/to_verify/structural` 状态 |
| `services/ahp.py` | 用 AHP 两两比较推导权重 | 输出一致性比率 CR；矛盾判断会被拒绝。特征向量法与几何平均法互验 |
| `services/sensitivity.py` | 权重 ±20% 扰动 × 1000，量化排名稳定性 | 输出 Spearman / Kendall / TOP-K 重合度，以及"哪些商品会摇摆" |
| `services/outcomes.py` | 导入"推荐→实际动销"配对样本，算命中率 | **样本 <30 条时拒绝给结论**，只给描述性统计 |
| `services/scoring.py` | 每个字段标注来源 | `measured / derived / default / missing`，估的值不再和实测的值长得一样 |

```bash
cd backend
python -m app.services.ahp            # 看权重推导过程与一致性检验
python scripts/run_sensitivity.py     # 跑扰动分析，写 reports/sensitivity.json
python -m pytest -q                   # 78 项测试
```

后台新增两页：**评分依据**（权重来源 + 稳健性 + 权重实验台）、**结果回流**（导入配对样本看命中率）。

### 当前的诚实状态

| 项 | 状态 |
|---|---|
| 门槛阈值已核实 | **0 / 6** 个 confirmed，全部待核实 |
| 核价门槛在演示集上的触发次数 | **0** 次（缺 `similar_lowest_price` 字段，该门槛根本没参与判定） |
| 命中率验证 | **无法计算**，配对样本 0 条 |
| AHP 一致性 | CR = 0.0092，通过 |
| 排名稳健性 | TOP-5 扰动 1000 次不变——**但这是演示数据近似重复造成的，不可外推** |
| 线上权重 | 仍是旧的拍板值。AHP 权重只推导展示，**未自动替换配置** |

完整口径与依据见 **[docs/评分标准.md](docs/评分标准.md)**。

## 阶段路线

- ✅ 第一阶段：无店铺 MVP（本仓库）
- ⬜ 第二阶段：公开趋势连接器、定时采集、历史趋势图（TrendSnapshot 已预留）、pgvector 聚类
- ⬜ 第三阶段：TEMU 官方授权接入，按实际开放权限启用同步
- ⬜ 第四阶段：统计人工采纳率，达标 FAQ 才能进入 L2 自动发送（开关与等级配置已就绪）
