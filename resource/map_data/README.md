# 地图结构化数据

> **2026-10 更新：游戏客户端的地图数据已同步进来（`client/`、`maps_client.json`，共 1171 张地图），规划和代理优先使用它；下面「识别方式」一节描述的截图识别结果（`maps.json`）保留作对照。见文末「客户端地图数据」。**

不再依赖完整地图图片：`maps.json`（每张图的格子类型和位置）+ `templates/`（地块模板）+ `tile_types.json`（类型说明）就够用。识别由 `tools/recognize_map_tiles.py` 完成，路线规划见 `tools/plan_route.py`，整批重建见 `tools/build_map_data.py`。

## 文件

| 文件 | 内容 |
| --- | --- |
| `maps.json` | 108 张地图（忘却篇第 1–9 章 88 张，特殊活动 20 张），共 2879 个格子 |
| `events.json` | 灰机 Wiki 剧情抄本的 367 条事件名与选项；281 条可关联现有地图，选项结果只抽取可明确识别的事实 |
| `map_evidence.json` | 108 张地图原图 SHA-1、事件关联覆盖、路线检查状态的逐图证据 |
| `live_observations.json` | 实机看到的事件选项和结果（目前只有 8-2），由 `tools/apply_live_observations.py` 合并进 `events.json` |
| `tile_effects.json` | 每种地块的规划属性（可否通行、是否需要钥匙、传送、代价权重）、效果说明、可信度和来源 |
| `route_check.json` | 108 张图的路线可达性检查结果 |
| `VALIDATION.md` | 对事件数据、地图证据的校验报告和 5-11 的修复说明 |
| `PLANNING.md` | 路线规划信息是否足够的评估和缺口 |
| `tile_types.json` | 32 种地块的名称、外观、功能说明与可信度、模板文件 |
| `templates/` | 62 个地块模板图（文件名 `<类型>_<序号>.png`） |

`maps.json` 每个地图：`id`、`series`（忘却篇 / 意识潜游 / 特遣记录）、`chapter` 或 `activity`、`stage`、`counts`、`tiles[]`。每个格子：`type`、`island`（互不相连的区域）、`row`/`col`（蜂窝格点，`col` 以半格为单位，相邻格相差 (0,±2) 或 (±1,±1)）、`x`/`y`（3508×1974 原图的像素坐标）。

## 识别方式与可信度

- 带图标的格子：梯度模板匹配（`TM_CCOEFF_NORMED` ≥ 0.64）。抽查了 一步之遥02、红色庆典、5-6、6-8、7-9、8-4、9-1、2-6、2-8、2-15、3-4、4-3 的叠加图，图标格基本全部识别正确。
- 无图标格（`plain`、`cracked_rock`、`purple_rift`、`red_flesh`）：从图标格向外按蜂窝格点逐格试探，再按颜色/纹理分类。这部分抽查中有漏判（个别裂纹石、红色格未标出）和误判（背景纹理，已删除 3-4 的两处），可信度低于图标格。
- 未做逐格人工校对。有疑问时可用 `python tools/recognize_map_tiles.py <图> --debug overlay.jpg` 出叠加图核对。
- 每张图的 `player` 应为 1：2-8 有两个头像水滴（橙光的那个用途不明）。
- 部分类型的标签文字随章节不同（联络点/联络处、析出点/亮晶晶），图标相同，已合并。

## 各分组的地块

| 分组 | 地图数 | 格子总数 | 专属/少见地块 |
| --- | --- | --- | --- |
| 意识潜游·一步之遥 | 1 | 26 | — |
| 意识潜游·如歌的雕琢 | 2 | 44 | — |
| 意识潜游·扭曲核心 | 1 | 27 | — |
| 意识潜游·燃烧的群宴 | 2 | 43 | — |
| 特遣记录·狩猎愉快！ | 1 | 23 | — |
| 特遣记录·蔷薇礼赞 | 9 | 172 | — |
| 意识潜游·血与沙 | 2 | 48 | — |
| 意识潜游·诸事如常 | 1 | 25 | — |
| 意识潜游·骑士的愿望 | 1 | 34 | — |
| 忘却篇 第1章 | 8 | 204 | 善意的礼物×3 |
| 忘却篇 第2章 | 12 | 314 | 未完的雕像×11 |
| 忘却篇 第3章 | 10 | 247 | 古怪脓疱×10 |
| 忘却篇 第4章 | 12 | 334 | 蜂蜜甜酒×12 |
| 忘却篇 第5章 | 10 | 293 | 代行之仪×8 |
| 忘却篇 第6章 | 10 | 263 | 纯白之帆×10 |
| 忘却篇 第7章 | 12 | 329 | 孕育之母×12 |
| 忘却篇 第8章 | 10 | 271 | 审查会探员×12、入学仪式×10、羁押点×9 |
| 忘却篇 第9章 | 4 | 98 | 审查会探员×2、入学仪式×4、羁押点×1 |

## 各类型总数

| 类型 | 名称 | 数量 |
| --- | --- | --- |
| `battle` | 战斗 | 362 |
| `plain` | 空白格 | 257 |
| `event` | 事件 | 248 |
| `contact` | 联络点 | 236 |
| `meltmark` | 融痕 | 165 |
| `illusion` | 幻象 | 147 |
| `locked_door` | 锈蚀门扉 | 144 |
| `searchlight` | 探照灯 | 126 |
| `cracked_rock` | 裂纹石格 | 113 |
| `player` | 当前位置 | 109 |
| `final_battle` | 最终战 | 108 |
| `tunnel` | 隧道 | 96 |
| `blackseal` | 黑印 | 88 |
| `extract` | 析出点 | 80 |
| `story` | 剧情 | 77 |
| `rusty_key` | 锈蚀钥匙 | 75 |
| `elite` | 精英 | 73 |
| `red_flesh` | 红色血肉格 | 53 |
| `oneway_in` | 单行密道 | 50 |
| `secret_exit` | 密道出口 | 50 |
| `purple_rift` | 紫蓝光格 | 34 |
| `inquisitor` | 审查会探员 | 14 |
| `enrollment` | 入学仪式 | 14 |
| `honey_wine` | 蜂蜜甜酒 | 12 |
| `mother_of_brood` | 孕育之母 | 12 |
| `unfinished_statue` | 未完的雕像 | 11 |
| `strange_cyst` | 古怪脓疱 | 10 |
| `white_sail` | 纯白之帆 | 10 |
| `detention` | 羁押点 | 10 |
| `proxy_rite` | 代行之仪 | 8 |
| `kind_gift` | 善意的礼物 | 3 |

## 没有的数据

- 地块的实际效果：只有锈蚀门扉/钥匙、事件、战斗、剧情、羁押点等少数确认，其余见 `tile_types.json` 的 `function_confidence`。
- 事件内的选项和结果：`events.json` 已提供关卡级先验资料，但通用事件图标无法判定具体触发哪一条事件；进入格子后仍要实机读取标题和选项。

## 事件与地图证据

`tools/build_event_data.py --wiki <灰机抄本缓存>` 从 Wiki 剧情页抽取事件名、选项标签和明确写出的传送、生命损失、症状、资源等结果，不收录剧情正文。输出保留每条来源链接、地图关联依据，以及“尚未实机核对”的状态。抄本缓存不随仓库分发；已生成的 `events.json` 含来源署名，须遵守原站的 CC BY-NC-SA 条款。

`python tools/audit_map_evidence.py` 对照灰机 API 清单校验 108 张原图 SHA-1，并生成逐图 `map_evidence.json`。本次 108 张均通过校验，103 张能关联至少一条事件，108 张在当前假设下可规划到终点。SHA-1 只能证明图片字节与来源一致，不能证明每个地块识别正确；事件列表也不能定位到某个具体问号格。

## 客户端地图数据（来自 Z769018860/qdby_chinese）

仓库 `Z769018860/qdby_chinese` 保存了从游戏客户端（Steam，运行时已加载的配置表，只读导出）筛选出的数据。`python tools/import_client_maps.py <该仓库的本地路径>` 把其中的地图相关部分同步进来（读 JSON，不执行那个仓库的任何代码）：

| 文件 | 内容 |
| --- | --- |
| `client/maps.json` | 1171 张地图的 8 行 × 13 列格子（0=墙，null=空地，整数=节点 id，列表=该格有多个随机变体） |
| `client/nodes.json` / `client/node_types.json` | 节点 id → 类型 / 战斗配置；80 种节点类型 → 本项目格子类型（`ours`） |
| `client/stages.json` | 5977 个关卡中带地图或线性节点序列的：名称、分类（主线/活动/融灾/幻梦深潜…）、等级、地图 id |
| `client/train.json` | 记忆回廊「疾驰的欢愉专列」路线（阶段 → 章节选项 → 节点） |
| `client/aliases.json` | 我们识别出来的 108 张图（`maps.json` 的 key）→ 客户端地图 id，含吻合度、偏移、逐格差异、同布局的困难/癫狂地图 |
| `maps_client.json` | 以上转换成规划器的蜂窝格点模型（island/row/col、格子类型、`alts` 随机变体、`hidden_event`） |
| `route_check_client.json` | 对全部地图跑规划器的结果（951 张可达、19 张需要推测的岛屿连接、309 张没有最终战） |

要点：
- 坐标：行 y=1..8（y=8 在最下方），列 x=1..13，奇数行向右错半格；格点 `col = 2*x + (y 为奇数)`，`row = -y`。配置里没有的格子是**空地**，节点「虚无」是**墙**。8-2 上与截图识别、实机结果逐格核对过。
- 与我们的截图识别对照（`python tools/compare_client_maps.py`）：108 张里 105 张吻合（很多是 100%）；主要差异：我们的「裂纹石」其实大多是**事件**格（147 处）、紫/红融蚀地面是**事件或恶沼**（53 处）、「监察点」是普通格外观的隐藏事件（7 处）；7-1、7-16、2-15 三张图的识别结果是错的（别的关卡的图），已按关卡 id 改指到正确的客户端地图。
- 新出现的格子类型：造物、银芯、影池、恶沼、监察点、随机节点（已写进 `tile_effects.json`，代价为推断值）。
- 同一关卡的普通/困难/癫狂版本布局相同时 `aliases.json` 的 `same_layout_maps` 列出它们。

没有的数据：
- 节点的效果表（传送去向、事件选项、扣血数值）不在导出的子集里，所以传送配对只能按「每图至多一对隧道/一对单行密道」推断（全部 1171 张图都满足），监察点→羁押点按 8-2 实机处理。
- 有 19 张图（幻梦深潜部分难度、祭礼、布朗出击、无妄的皈依等）的起点和终点在互不相连的岛上，数据里没有它们之间的连接（应当是事件传送）；规划器会按最近格加推测桥接并标记。

## 幻梦深潜 layouts, live facts and the event catalogue

- `dive_layouts.json` (`tools/build_dive_layouts.py`): the 24 layout styles of each 篇 (忘却篇 / 星辰篇) with client map id,
  node counts, the stages (difficulty I–VII, 癫狂 at lv 64–80) that use each and the route-check status. A run draws one
  layout at random (live fact `dive_random_layout`), so the agent identifies it from the first screens
  (`Knowledge.identify_map` / `Navigator.try_identify`) and then routes on the exact map. In the unknown-map simulation
  this lifted the success rate from 75.7% to 90.0%.
- `live_facts.json`: what the live dive runs showed (door re-tap, one-way passages, reward popup, 融痕 shop prices, result
  page, checkpoint has no passage; the opening popup is still unverified).
- `events_all.json` (`tools/build_event_catalog.py`): every known event merged with its client node kind, maps and live
  evidence, plus all 51 tile kinds and the 24 event kinds that have no wiki text yet.

## 活动关与记忆回廊目录

`tools/build_stage_catalog.py` 生成:
- `activity_stages.json`:客户端全部「活动 / 支线」关卡按活动汇总(50 个活动,关卡数、等级范围、关卡 id),并列出本项目已有的活动配置(`our_profiles`)。客户端活动名按角色/活动 id 命名,与游戏内标题没有自动对应。
- `train_corridor.json`:记忆回廊路线——3 种难度(普通/困难/癫狂),每条路线 初始化 + 三次共鸣阶段,每阶段从 4 个章节里抽一个;每章的节点序列(固定事件、褪色遗骨、灰烬遗迹、随机节点及其变体数)。
- `events_all.json` 的 `train_events`:各章固定事件(未完的蜡像、直面深渊、终站将近等),其中多数还没有选项文本,需要实机截图补齐。

## 怪物行动意图

`monster_intents.json`(`tools/build_monster_intents.py`,数据来自客户端本地配置导出):492 个怪物、1153 个技能。每个怪物有 `opening`(首轮行动)和 `cycles`(循环 1..n),每个技能带游戏内意图名(如 封印=强力削弱、追猎=强力攻击)、图标编号(`resource/image/intent/intent_NNN.png`)、目标和官方描述;融灾怪物另带各等级数值,可填出「造成 886 点伤害 3 次」。
- 文本查看:`cd agent && python3 -m morimens_logic.intents 撕裂维度之足 --level 99`(格式同 wiki 的「行动意图 / 技能详情」)。
- 图文页面:`docs/monster_intents.html`(含图标、箭头流程和技能表,重新生成:`python3 -c "…intents.html_page()"` 见 `agent/morimens_logic/intents.py`)。
