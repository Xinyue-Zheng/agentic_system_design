# 多智能体电信网络停机影响评估系统
## 完整系统说明

---

## 系统概述

本系统以原始停机工单作为输入，通过协调七个专业 Agent 的分工协作，输出结构化的影响评估报告——包含严重性评级、处置建议和面向工程师的自然语言摘要。每个 Agent 只负责一个分析维度，最终结论由所有 Agent 的输出综合产生。

整个流水线由 Python Harness 编排，负责 Agent 的顺序与并行调度、Skill 文件注入以及 Human-in-the-Loop（HITL）升级触发。所有分析 Agent 通过磁盘上的结构化 JSON Artifact 进行通信，不读取彼此的中间状态或原始推理过程。

---

## 系统架构

```
工单（JSON）
    │
    ▼
本地预处理  ──────────────────────────────────────────► preprocessing_stats.json
    │                                                    （RF 覆盖统计、吸收比例、容量得分）
    ▼
Context Planner ─────────────────────────────────────► planner_output.json
    │                                                    （shared_context、per_agent_context）
    │
    ├──────────────────┬──────────────────┐
    ▼                  ▼                  ▼         （并行）
Coverage Agent      KPI Agent         Config Agent
    │                  │                  │
    ▼                  ▼                  ▼
Per-Agent         Per-Agent         Per-Agent
Verifier          Verifier          Verifier
    │
    ▼
Geo Agent ──────────────────────────────────────────（等待 Coverage 完成）
    │
    ▼
Per-Agent Verifier
    │
    ▼
Assessment Agent
    │
    ▼
Per-Agent Verifier
    │
    ▼
Cross-Agent Verifier ── [重大矛盾] ──► 自动重跑一次 ──► [仍有矛盾] ──► HITL
    │
    ▼ （通过）
Reflector ───────────────────────────────────────────► memory_store.json
```

---

## 数据基础设施

### MCP Server

所有 Agent 通过本地 MCP（Model Context Protocol）Server 访问数据。Server 暴露以下工具：

| 工具 | 数据内容 | 调用方 |
|---|---|---|
| `get_kpi_history(usid)` | 60 天逐 sector 吞吐量历史 | Planner、KPI Agent |
| `get_kpi_timeseries(usid, start, end)` | 指定时间窗口内逐 sector 吞吐量 | Planner |
| `get_coverage_pixels(usid)` | 站点覆盖像素数据 | Coverage Agent |
| `get_coverage_pixels_by_sector(sector_id)` | 指定 sector 的像素数据 | Coverage Agent |
| `get_preprocessing_stats(usid)` | 预计算的 RF 和负载统计 | Coverage Agent |
| `get_site_attributes(usid)` | 单站点硬件配置 | Config Agent |
| `get_all_site_attributes()` | 所有站点硬件配置 | Config Agent |
| `get_geo_features(lat, lon, radius_km)` | OpenStreetMap 瓦片图（base64 PNG） | Geo Agent |
| `get_area_profile(lat, lon, radius_m)` | 结构化 OSM 土地类型数据（Overpass） | Planner |

### 本地预处理

在任何 Agent 启动之前，一个 Python 函数处理原始覆盖像素数据和站点属性，生成 `preprocessing_stats.json`，包含：

- **逐 USID RF 统计**：主导像素比例、RSRP p10/p50/p90、推断站点角色（dominant-anchor / strong-supporting / localized-supporting / edge-limited）
- **负载重分布分析**：对目标 USID，哪些邻居提供备份覆盖、每个邻居的 `absorption_fraction_of_target`（目标像素中以该邻居为 backup1 的比例）、切换质量、停机后负载系数、超载风险
- **逐 sector 细分**：像素数、RSRP p50、所属 USID 映射
- **容量评分**：基于硬件的站点容量得分，公式：`(4G小区数 × 1.0 + 5G小区数 × 2.0) × (1 + 0.15 × 有效频段数)`
- **RSRP 和 SINR 图像**：供 Coverage Agent 视觉分析使用

预处理仅使用本地数据，不调用任何 API，运行时间以秒计，结果具有确定性。

---

## Agent 详细说明

---

### 1. Context Planner

**职责**：在任何分析 Agent 启动之前，为本次停机建立分析情境。Planner 的输出成为所有下游 Agent 共享的指令集。

**为什么用 Agent 而不是代码**：Planner 必须在不完整信息下做决策。工单是半结构化文本，质量参差不齐。哪些 sector 真正失效、停机时间是否异常、地理影响范围多大——这些关键判断无法用固定规则解决。Planner 作为 ReAct Agent 运行，根据工单内容动态选择工具调用策略。

**推理内容**：

*Q1 — Sector 状态分类*：当 Partial Outage 工单没有明确列出受影响 sector 时，Planner 必须从数据中判断。它调用 `get_kpi_history` 建立 60 天基准，再调用 `get_kpi_timeseries` 观察停机窗口内的实际吞吐量。分类阈值（低于基准 5% = failed，5-60% = degraded，超过 60% = active）是固定的，但边界情况需要推理：某 sector 的数据稀疏怎么处理？停机发生在时间窗口中途，时间序列同时包含停机前后的数据怎么判断？这些边界情况是 hardcode 规则无法预见的。

*Q2 — 峰值时段识别*：每个站点的繁忙时段因用户构成和地理位置而异。Planner 按小时聚合该站点 60 天的历史吞吐量，找出周期性高需求时段，然后判断这些时段是否落在停机窗口内。凌晨 3 点的停机和晚上 6 点的停机影响截然不同，这个区分必须准确传达给 KPI Agent。

*Q3 — 地理影响范围*：纯推断，无需工具调用。Full Outage → 所有方向受影响；有 failed sector → 特定方向受影响；仅 degraded → 最小地理影响。Planner 应用规则并设置相应的 geo_scope_flag。

*Q4 — 时间背景与区域画像*：Planner 调用 `get_area_profile`，获取停机站点坐标周围的结构化 OpenStreetMap 数据（土地类型构成、是否有医院/学校）。同时判断停机是否落在美国节假日、周末或工作日，以及一天中的哪个时段。这个情境对 KPI Agent 的流量预测至关重要：节假日住宅区和工作日商业区的流量模式差异巨大，而 60 天历史均值可能无法反映这种差异。

**输出**：`planner_output.json`，包含 `shared_context`（sector 状态、峰值时段、时间背景、区域画像、地理范围）和 `per_agent_context`（每个 Agent 的优先重点、flag 和约束）。

**Skill 文件**：`planning_rules.md`、`output_schema.md`、所有四个 `context_rules/*.md`

---

### 2. Coverage Agent

**职责**：评估停机的信号层影响。被迁移的用户还能从邻居小区收到可用的无线信号吗？

**为什么用 Agent 而不是代码**：这个 Agent 有两项任务本质上需要 LLM 推理。第一，预处理生成的 RSRP 热力图必须进行视觉解读——哪些方向信号强、覆盖在哪里减弱、这在空间上意味着什么——这种图像到语言的转换无法用程序实现。第二，在分析特定 sector 的方向性覆盖时，Agent 必须解读覆盖像素的空间分布，理解哪些地理方向受影响以及备份信号质量如何在这些方向上变化。

**推理内容**：

*信号质量分析*：对每个邻居站点，Agent 读取 RSRP 热力图，用方位语言描述信号从强到弱的分布（"NW 方向在 USID_09 主导边界内信号 excellent，SE 方向在边界处降至 weak"）。这是整个系统中唯一需要图像分析的字段，其描述结果供 Geo Agent 决定在地图上重点分析哪里。

*负载重分布评估*：Agent 读取预处理统计数据——吸收比例、切换质量、停机后负载系数、超载风险——综合判断邻居覆盖是 adequate、strained 还是 overloaded。这个结论取决于多个信号的组合：覆盖空洞比例（多少像素没有 backup）、切换质量（backup 区域信号质量如何）、超载风险（每个邻居承担多少额外负载）。这些信号无法归结为单一规则，Agent 必须综合权衡。

*方向性空间分析*（Directional Focus Skill — 有 sector 失效时加载）：Agent 对每个失效或降级 sector 调用 `get_coverage_pixels_by_sector`，计算该 sector 像素分布的地理重心和边界框，生成 `per_zone` 条目。这些重心坐标传给 Geo Agent，确保其地图请求精确地以受影响区域为中心，而不是笼统地以铁塔为中心。

**Skill 文件**：`coverage_analysis_base.md`（永远加载），`coverage_directional_focus.md`（FULL_SITE_FAILURE 或 PARTIAL_SECTOR_FAILURE 时加载）

**输出**：`load_redistribution_verdict`、`coverage_hole_fraction`、`per_backup` 统计、`key_findings_for_geo`、`per_zone`（sector 重心和信号状况）、`reasoning_log`

---

### 3. KPI Agent

**职责**：评估停机的流量层影响。邻居站点能否承接被迁移的流量？这种承接在整个停机持续时间和峰值时段内是否成立？

**为什么用 Agent 而不是代码**：KPI Agent 本质上是一个**不确定性下的预测问题**，而不是查表。它必须用历史数据估算假设情境下（该站点停机）的流量变化。难点在于历史均值可能无法反映当前时刻：节假日、周末、一天中的时段、受影响区域的土地类型构成，都决定了基准是否是好的预测器。决定使用哪段历史数据、如何调整、以及如何清晰说明由此产生的不确定性，都需要情境推理。

**为什么不能是纯代码**：关键步骤——基于时间背景和区域画像调整流量预测——涉及多因素加权组合（节假日类型 × 土地类型构成 × 一天中的时段），需要产生可审计的自然语言推理。Per-Agent Verifier 会检查所声明的调整是否与观测到的情境一致。Hardcode 公式只能产生数字，无法产生可审计的推理过程。

**推理内容**：

*时间情境基准选择*（Step 0 — 时间背景）：Agent 读取 `shared_context.time_background` 和 `area_profile`。如果停机发生在感恩节的住宅区，60 天历史均值（以工作日数据为主）会低估实际流量需求 20-30%。Agent 必须识别这种错配，根据土地类型构成选择合适的调整系数，并记录原因。关键是，当调整本身不确定时也必须明确标注：如果 60 天窗口内只有一两个节假日数据点，调整系数本身就缺乏依据，这必须在 `calibration_note` 中说明。

*流量损失估算*：对失效 sector，Agent 使用与停机时段匹配的历史均值（按停机所在小时筛选，而非 24 小时整体均值）估算丢失的吞吐量。对 Partial Outage，活跃 sector 的流量损失为零。Step 0 的调整系数应用于产生情境感知的估算。

*邻居容量压力估算*：对每个邻居，Agent 获取历史基准和 p90 吞吐量（90 分位数，用作观测到的容量上限代理）。将丢失的流量乘以邻居的 `absorption_fraction`（来自预处理），估算该邻居需要承接的额外负载。将 `new_total` 与 p90 比较，将容量压力分类为 low、moderate、high 或 critical。**关键：这是压力信号而非确定性结论**——p90 是统计观测值而非硬性上限，实际网络可能承受超过 p90 的压力，具体取决于硬件余量。Agent 必须在 `overload_risk_note` 中明确说明这一点。

*多层时间维度分析*：Base 分析给出单一窗口均值结论。两个附加 Skill 层以更精细的时间粒度扩展分析：
- **Peak Hour Skill**（`peak_overlap=true` 且 `duration ≤ 6h` 时加载）：仅使用峰值时段的历史子集重新运行容量压力分析。峰值时段邻居本身负载更高，额外吸收的流量在邻居余量最少时到来——这可能暴露出窗口均值所掩盖的 critical 压力情况。
- **Sustained Pressure Skill**（`duration > 6h` 时加载）：将停机切分为逐小时段，对每个小时应用该时段的历史基准，逐小时分类为 stable、stressed 或 overloaded。从逐小时分布中派生 `peak_hour_verdict`（避免重复运行 Peak Hour Skill）。识别趋势：压力是在恶化、稳定还是在改善？

**Skill 文件**：`kpi_analysis_base.md`（永远加载），`kpi_peak_hour_analysis.md`（条件加载），`kpi_sustained_pressure.md`（条件加载）

**输出**：`overload_risk`、`lost_traffic_mbps`、`time_background_applied`、`per_neighbor` 压力评级、`peak_hour_verdict`、`sustained_pressure_verdict`、`hourly_distribution`、`reasoning_log`

---

### 4. Config Agent

**职责**：评估邻居站点的硬件层容量。物理基础设施能否支撑承接被迁移的负载？

**为什么用 Agent 而不是代码**：可行性规则（容量得分阈值、运营角色分类）是确定性的，原则上可以用代码实现。Agent 的推理价值来自两个地方。第一，在特定停机情境下解读硬件配置的含义——例如，micro 站（20m 铁塔）在硬件上被分类为 feasible，但其覆盖半径有限；Agent 必须认识到这一物理约束可能使硬件评估失效，如果该站无法覆盖到被迁移的用户。第二，NSA 5G 降级风险分析需要推理哪些用户面临风险：并非所有失效站用户都会被迁移到 4G-only 邻居，只有切换方向恰好朝向该邻居的用户才会，这取决于 sector 几何结构。

**推理内容**：

*硬件容量评分*：读取站点属性（小区数、频段、铁塔高度、运营角色），计算归一化容量得分。根据得分和角色将每个邻居分类为 feasible、marginal 或 infeasible。记录具体匹配了哪条规则以及原因。

*物理覆盖范围推理*：当 micro 站被分类为 feasible 时，Agent 标注其 20m 铁塔限制了地理覆盖半径，并与 Coverage Agent 的 `per_zone` 重心交叉参考，评估该站是否能实际覆盖到被迁移用户所在区域。

*NSA 5G 降级风险*：如果失效站有 5G 小区且某邻居没有 5G 小区，被迁移至该邻居的用户将从 5G NR 降回 4G LTE。Agent 计算估算受影响比例并点名造成这一缺口的具体邻居。

**Skill 文件**：`config_analysis_base.md`（永远加载，无条件扩展）

**输出**：`overall_capacity_verdict`、`per_neighbor` 可行性评级、`nsa_5g_downgrade_risk`、`reasoning_log`

---

### 5. Geo Agent

**职责**：确定停机的地理和土地类型情境。哪种地方失去了覆盖？这对受影响用户意味着什么？

**为什么用 Agent 而不是代码**：这里有两项任务本质上依赖 LLM。第一，OpenStreetMap 地图瓦片是栅格图像；从视觉地图特征识别土地类型（住宅、商业、医院、森林）——通过街道网格模式、彩色区域、标注建筑、红十字符号——需要视觉理解，任何基于规则的系统都无法可靠实现。第二，空间叠加判断——覆盖空洞的地理位置是否与能解释信号缺失的地形特征重合——需要理解以不同格式描述的两组地理特征之间的空间关系。

**推理内容**：

*sector 精准地图请求*：不是请求一张以铁塔为中心的 10km 地图，而是使用 Coverage Agent 提供的 `per_zone` 重心，请求以每个受影响 sector 的像素分布中心为圆心的 3km 地图，确保地图捕捉到用户实际失去服务的区域。

*基于视觉证据的土地类型分类*：对每个 HIGH 优先级区域（失效 sector、覆盖空洞），Agent 视觉检查地图瓦片，仅从可观察的特征分类土地类型——绝不从信号模式推断。医院：红十字符号或明确标注。学校：校园布局或运动场地。住宅：规则街格配较小建筑。森林：绿色阴影区域配公园标注。Agent 记录支撑每个分类的具体地图特征，使推理可审计。

*地形-信号关联*：如果某区域的地图显示森林或溪流，而该区域恰好存在覆盖空洞，Agent 判断地形是否在地理上与空洞位置重叠。森林衰减（+8 dB）和溪流衰减（+4 dB）可以解释 RF 数据中看起来异常的信号缺失。这种跨数据源的空间推理——将 RF 结果（覆盖空洞）与地理特征（森林边界）通过地图图像连接——是该 Agent 最独特的能力。

*用户影响评估*：仅基于土地类型评定用户相关度：critical（医院、学校），high（住宅、商业），medium（主要道路），low（森林、工业）。还分析邻居铁塔位置，判断覆盖关键区域的邻居是否有刚性流量需求，可能使 KPI 容量估算偏于乐观。

*自设 flag*：Agent 根据地图观测自行设置 `terrain_attenuation_active` 和 `high_sensitivity_area`，而非接受 Planner 的预判。这些 flag 传播至 Assessment Agent，可能触发严重性升级。

**Skill 文件**：`geo_analysis_base.md`（永远加载，无条件扩展）

**输出**：`per_zone` 土地类型和用户相关度、`per_backup_zone` 需求画像、`self_flags`、`key_findings_for_assessment`、`reasoning_log`

---

### 6. Assessment Agent

**职责**：将四个专业 Agent 的结论综合为单一严重性评级、处置建议和执行摘要。

**为什么用 Agent 而不是代码**：Assessment Agent 的核心任务是在冲突中推理。实践中，专业 Agent 经常意见相左：Coverage 可能报告备份信号充足，而 KPI 报告流量压力严峻；Geo 可能标注敏感区域，而 Config 报告硬件充裕。这些冲突无法用查表解决。Agent 必须理解每个冲突的性质——是真正的矛盾、还是各 Agent 测量不同事物的必然结果、还是某 Agent 的假设在此情境下失效的迹象——并判断如何权衡各信号。

**推理内容**：

*多维冲突解析*：Agent 收集四个主要结论（coverage 负载重分布、KPI 超载风险、config 容量、geo 升级标志），识别其方向和幅度。当结论一致时，置信度高。当结论分歧时，Agent 推理原因：Coverage adequate + KPI 高压通常反映空间代理的局限性（像素承载的流量并不相等）；Geo 升级且 coverage 压力低，反映信号质量并不决定人群脆弱性。Agent 解释每个冲突的性质，而不是将其平均化处理。

*带证据的严重性规则应用*：P1/P2/P3 规则是明确的，但应用时需记录哪个具体条件被满足以及触发的数值。Agent 依次检查所有五个 P1 条件和所有 P2 条件，引用输入结论中的精确数值。这使严重性评级完全可审计——Per-Agent Verifier 可确认所有条件均已检查且声明的数值与 Artifact 匹配。

*地理升级覆盖*：如果 `high_sensitivity_area=true`，无论其他结论如何，严重性不得为 P3。如果 `terrain_attenuation_active=true`，处置建议必须注明受影响区域的实际信号质量比 RF 测量值更差。这些覆盖规则是确定性的，但正确应用需要理解 Geo 结论。

*不确定性传播*：KPI Agent 现在输出压力信号而非二元超载结论，并明确标注估算存在较高不确定性的情况（节假日调整数据稀疏、森林覆盖区域吸收比例不可靠）。Assessment Agent 必须将这种不确定性纳入置信度评级，并解释 KPI 不确定性如何影响最终结论。

*自然语言综合*：最终输出包含一段 2-3 句话的摘要，面向网络运营工程师——描述发生了什么、四个维度的综合影响是什么、需要采取什么行动。将技术结论综合为可执行的语言是 LLM 的核心能力。

**Skill 文件**：`assessment_agent.md`（永远加载，无条件扩展）

**输出**：`overall_severity`、`severity_reasoning`、`recommended_action`、`confidence`、`confidence_reasons`、`summary`、`key_findings`、`secondary_signals`、`reasoning_log`

---

### 7. Per-Agent Verifier

**职责**：在每个分析 Agent 完成后立即运行，检查该 Agent 的推理是否内部自洽，以及其声明的假设是否适合当前场景情境。

**为什么用 Agent**：Verifier 执行两类本质上不同的检查。**A 类检查**是确定性规则应用（verdict_scope 是否与 outage_type 匹配？可行性规则是否正确应用了声明的容量得分？）——这些可以用代码实现，在此纳入统一报告。**B 类检查**需要情境推理：给定观测到的场景（节假日、森林为主的区域、micro 站），Agent 声明的假设是否成立？这种假设-情境矛盾检测，正是 LLM 幻觉风险较低（输入结构化、问题具体、答案有依据）而价值较高（代码无法推理假设是否情境适用）的任务类型。

**推理内容**：

*假设-情境一致性*：Verifier 读取 Agent `reasoning_log` 中每个 `assumption` 字段，与 `shared_context.area_profile` 和 `time_background` 对照检查。例如：当 `area_profile.dominant_landuse = forest` 时，Coverage Agent "流量与像素成正比"的假设值得质疑（森林像素每像素承载的流量远低于住宅像素）。当 `day_type = holiday` 但 `calibration_note = null` 时，KPI Agent 的基准调整存疑（60 天窗口中节假日数据点稀少，这种不确定性必须被承认）。Verifier 不泛泛评判分析质量，而是识别声明假设与可观察场景事实之间具体的、有依据的矛盾。

*规则合规性*：检查确定性规则是否被正确应用：verdict_scope、可行性阈值、geo 升级覆盖、所有 P1 条件均已记录。这些是机械性检查但很重要；此处的错误会悄无声息地传播至最终结论。

*不确定性标志传播*：当 B 类检查发现假设不一致时，Verifier 在 `flags_for_cross_verifier` 中记录标志。Cross-Agent Verifier 读取这些标志，并在跨 Agent 一致性检查中加以参考。

**输出**：逐 Agent 验证 JSON，包含 `overall`（pass / pass_with_warnings / fail）、带证据和建议的 `checks` 列表、`flags_for_cross_verifier`、`uncertainty_upgrade_recommended`

---

### 8. Cross-Agent Verifier

**职责**：在所有五个分析 Agent 完成并经过独立验证后，检查它们的结论是否相互一致。

**检查内容**：

| 检查 | 检测对象 |
|---|---|
| Coverage ↔ KPI | 信号充足但流量严峻：空间代理可能低估负载。Coverage=adequate 且 overload_risk=critical 时标注 |
| Coverage ↔ Geo | 覆盖空洞无地形解释：可能是网络规划缺口而非 RF 模型局限 |
| KPI ↔ Config | 硬件充足但 KPI 压力高：不是矛盾，但是有意义的分歧（标注 fragile_capacity 或 config_bottleneck） |
| Geo ↔ Assessment | 受影响区域有关键基础设施但严重性为 P3：geo 升级规则未正确应用 |
| Assessment 内部 | P1 条件满足但严重性≠P1：Assessment 规则应用错误 |

**HITL 升级逻辑**：
- Minor 差异 → 记录注释，继续
- Major 差异（首次）→ 自动重跑涉及 Agent 一次，提示中加入差异描述
- Major 差异（重跑后）→ 生成 `ESCALATION_REQUIRED.txt`，暂停 pipeline，等待人工审核
- Check 4 或 5 为 Major → 立即 HITL，不重跑（Assessment 逻辑错误无法通过重跑分析 Agent 修复）

**输出**：Cross-agent verifier artifact，包含逐检查结果、`overall_result`（pass / rerun / hitl）、`reflector_payload`

---

### 9. Reflector

**职责**：在完整 pipeline 结束后，将本次运行的发现综合写入持久化记忆条目，帮助未来的运行更准确。

**工作内容**：

*运行质量评估*：评估 Planner 的工具调用是否合理、Agent 差异是否得到解决或升级、什么导致了置信度下降。

*Ground Truth 对比*：对 RESOLVED 工单，从 `resolution_notes` 推断实际严重性（紧急派工 = P1，下次维护窗口 = P3），与预测严重性对比，记录准确性。

*跨运行模式识别*：Reflector 在写入前读取现有 `memory_store.json`。它能识别重复出现的模式——例如，连续三次运行都出现 KPI-Config minor 差异后，将其记录为确认的稳定非告警模式。这种跨运行学习只有在每次运行的发现结构化且累积的情况下才能实现。

*教训提炼*：产生 1-3 条具体的、有行动意义的观察，基于本次运行的具体发现。不是泛泛而谈（"Agent 有时意见不一"），而是场景化的具体观察（"郊区住宅区 Partial Outage 站点的 KPI-Config minor 差异是稳定的良性模式——第三次出现，不需要 HITL"）。

**输出**：`reflector_output.json`（运行摘要），更新后的 `memory_store.json`（新条目 + 更新后的汇总统计）

---

## Skill 加载汇总

| Agent | Base Skill | 条件扩展 Skill | 触发条件 |
|---|---|---|---|
| Planner | planning_rules.md + output_schema.md | — | — |
| Coverage | coverage_analysis_base.md | coverage_directional_focus.md | FULL_SITE_FAILURE 或 PARTIAL_SECTOR_FAILURE |
| KPI | kpi_analysis_base.md | kpi_peak_hour_analysis.md | peak_overlap=true 且 duration ≤ 6h |
| KPI | kpi_analysis_base.md | kpi_sustained_pressure.md | duration > 6h |
| Config | config_analysis_base.md | — | — |
| Geo | geo_analysis_base.md | — | — |
| Assessment | assessment_agent.md | — | — |
| Per-Agent Verifier | per_agent_verifier.md | — | — |
| Cross-Agent Verifier | cross_agent_verifier.md | — | — |
| Reflector | reflector.md | — | — |

---

## 核心设计原则

**What-if 预测，而非事后归因**：KPI Agent 仅使用历史数据估算流量影响，即使对 RESOLVED 工单（停机窗口内的数据已存在）也不例外。使用实际停机窗口内邻居的 KPI 数据会将 ground truth 污染进预测——系统等于"提前看了答案"。

**压力信号，而非二元结论**：KPI 输出容量压力评级（low / moderate / high / critical），而非二元超载/非超载结论。这反映了基于 p90 估算的真实不确定性，使 Assessment Agent 能将 KPI 发现与其他信号适当地权衡。

**显式假设记录**：每个 Agent 在 `reasoning_log` 中记录其假设。这服务于两个目的：使验证任务可行（Per-Agent Verifier 对照场景情境检查声明的假设），以及支持诚实的不确定性量化（情境不适用的假设自动传播为更高的不确定性评级）。

**分层验证**：Per-Agent Verification 在源头捕捉假设-情境矛盾和规则合规错误。Cross-Agent Verification 捕捉 Agent 间的一致性失败。Human-in-the-Loop 处理自动检查无法解决的情况。这种分层设计意味着没有单一验证机制需要完美。

**记忆驱动学习**：Memory Store 跨运行累积发现。重复出现的模式（如每次 Partial Outage 运行都出现 KPI-Config minor 差异）被识别并记录为预期行为，降低未来运行的虚假告警。RESOLVED 工单的 Ground Truth 对比随时间校准严重性预测准确率。
