# 通用事件与地图逻辑

自动走地图、处理事件、商店购买、造物/刻印/卡牌选择、联络点、战斗失败，并保证不会卡死。与 MaaFramework 解耦：由适配器把截图变成 `Observation`，引擎返回 `Action`，适配器去执行。

> **状态：逻辑层已写好并在模拟环境里验证，没有接入真实游戏。** 引擎还没有和 `interface.json` 的任务或 MaaFramework 的识别连接，识别屏幕类型、读事件标题和选项、定位格子都要适配器实现（见下文「接入」）。模拟环境里的游戏规则是我的假设，不是真实规则。

## 目录

| 路径 | 内容 |
| --- | --- |
| `morimens_logic/policy.py` | 设置的加载、合并、校验 |
| `morimens_logic/decisions.py` | 事件选项、商店购买、造物/刻印/卡牌选择、联络点、失败处理（纯函数） |
| `morimens_logic/navigator.py` | 地图路线：每步按当前位置重新规划；没有地图先验时边走边学 |
| `morimens_logic/guard.py` | 卡死检测与逐级升级 |
| `morimens_logic/engine.py` | 把上面组合成 `step(obs) -> Action` |
| `morimens_logic/sim.py` | 模拟游戏，用来验证引擎 |
| `tests/test_logic.py` | 单元测试（22 项） |
| `../resource/explore/policy.default.json`、`presets/` | 默认设置和三个预设 |
| `../config/explore_policy.example.json` | 用户设置示例 |

## 设置

设置按「默认 ← 预设 ← 用户文件」合并。把 `config/explore_policy.example.json` 复制成 `config/explore_policy.json` 再改，只需写要改的项。

```
python -m morimens_logic.policy --validate config/explore_policy.json   # 检查拼写和取值
python -m morimens_logic.policy --show --preset greedy                  # 查看最终生效的设置
```
（在 `agent` 目录下运行。）拼写错误的项会警告，取值不合法会拒绝加载，不会静默忽略。

预设：`conservative` 保守（避开精英/幻象/危险格，低血量就找联络点，只买 1 件）、`balanced` 默认、`greedy` 激进（顺路拿事件和钥匙，买满）。

| 设置 | 作用 |
| --- | --- |
| `route.avoid.<地块>` | 路线代价倍数，越大越绕开；例如 `elite: 5` |
| `route.allow_hazard` | `false` 时幻象/紫蓝格代价乘 1000（仍可在别无通路时走） |
| `route.use_searchlight` | 顺路踩探照灯 |
| `route.visit_contact_below_hp` | 血量低于此值时优先去联络点，无视绕路限制 |
| `route.must_visit` | 顺路必访的地块类型，如 `["event","rusty_key"]`；受 `max_detour_cost` 限制 |
| `route.key_policy` | `pick_when_needed` 门挡路才取钥匙 / `always_pick` 总是取 / `never` |
| `route.unknown_map_priority` | 不知道是哪一关时，可走格的类型优先级 |
| `event.choice_mode` | `best_score` 按效果打分 / `leave` 优先离开 / `first` / `last` |
| `event.weights` | 各效果的权重：得造物、得刻印、回血、受伤、得症状、传送…… |
| `event.hp_guard` | 血量低于此值时，受伤和症状的惩罚加重、回血加成翻倍 |
| `event.overrides` | 按事件名指定偏好/回避选项，如 `监察点: prefer 离开` |
| `event.blind_choice` | 读不到选项文字时按位置选：`first`/`middle`/`last`（默认最后一项，与原流程一致） |
| `event.tie_break` | 分数相同时选离开/第一项/最后一项 |
| `shop.mode` | `none` 不买 / `first` 只买第一个 / `all` 买全部 / `priority` 按名称优先级 |
| `shop.max_purchases`、`reserve_currency` | 最多买几件、至少留多少货币 |
| `shop.priority_names`、`skip_names` | 优先买/不买的名称（模糊匹配） |
| `shop.position_order`、`unaffordable` | 无名称时的位置顺序；价格变红时 `skip` 跳过 / `stop` 停止购买 |
| `pick.artifact/seal/card` | 三选一的名称优先级、回避词、位置顺序 |
| `contact.heal_below_hp`、`otherwise` | 血量低于此值回血，否则 `awaken`（觉醒）或 `heal` |
| `battle.use_revive`、`on_defeat` | 失败时是否用灵知复活，否则撤退 |
| `stuck.*` | 卡死处理阈值，见下 |

## 防卡死

引擎每步都有后备，最差也是明确停止并说明原因，不会无限重试：

1. **同一画面重复**（指纹不变）按次数升级：重试 → 换一个动作（换选项/换格子/点空白）→ 回退（返回键）→ 放弃并报告。阈值是 `stuck.same_state_retry/alternate/recover`。
2. **走回头路**：同一格进入超过 `stuck.max_tile_entries` 次（没有地图先验时放宽 3 倍）就停止并报告「loop」；路线代价也会随重复次数上升，促使换路。
3. **点击没生效**：每格点击失败超过 `max_attempts_per_tile` 次后拉黑该格并重新规划；锁门点不开时会修正「我有钥匙」的判断，回去再取。
4. **未知画面/加载**：先等，再点空白、关闭弹窗、返回；超过 `max_unknown_steps` 放弃。
5. **失败后换选项**：战斗失败撤退后再次遇到同一格的事件，会避开上次的选项。
6. **全局步数上限** `stuck.max_steps_per_map`。

放弃时 `Action(STOP, "stuck"|"loop"|"completed", 说明)` 是最后一个动作；`"completed"` 表示正常通关。

## 模拟验证

```
cd agent
python -m unittest discover -s tests
python -m morimens_logic.sim --maps all --presets conservative,balanced,greedy --seeds 3
python -m morimens_logic.sim --maps all --no-text --unknown-map --noise 2    # 更苛刻的情形
```

模拟器用真实的 108 张地图和 `events.json`，并注入故障：8% 点击无效、4% 无法识别的画面、5% 随机弹窗、10% 定位失败。假设（未经实机验证）：战斗/事件/联络点/商店/刻印/卡牌的流程见 `sim.py` 文件头。

最近一次结果（每组 3 个随机种子）：

| 情形 | 成功率 |
| --- | --- |
| 默认故障率（传送入口强制传送；26 张在该假设下无解的图不计入） | 738 / 738 |
| 单行密道/隧道不强制传送（108 张全部参与） | 972 / 972 |
| 读不到选项文字 | 737 / 738 |
| 不知道是哪一关（边走边探索） | 730 / 738 |
| 故障率 ×3 | 735 / 738 |
| 读不到文字 + 不知道哪一关 + 故障率 ×2 | 728 / 738 |

失败的情形都是引擎在放弃时明确停止（`loop`/`stuck`），没有无限循环。

## 发现的地图问题

模拟暴露了一个数据层的矛盾：如果「踏上单行密道/隧道入口必定传送」，108 张图里有 26 张**永远走不到最终战**（最终战常紧邻入口格）。所以引擎默认不假设强制传送，而是运行时学习：第一次踏上入口格后看落点，落在出口就记为强制传送并重新规划，留在原地就记为可选。真实规则需要实机确认。

## 接入

实现 `adapter.GameAdapter` 的两个方法，然后：

```python
from morimens_logic.adapter import run
from morimens_logic.engine import Engine
result = run(MyAdapter(), Engine(map_id="5-6"))   # map_id 可省略
```

适配器要做的：

- `observe()`：判断当前屏幕类型（`Screen`）、地图上的玩家位置、可进入的格子、事件标题和选项文字（没有 OCR 就用 `[None]*n` 只给数量）、商店价格是否变红、血量比例；并给出画面指纹 `fingerprint`（例如缩小截图的哈希），引擎靠它判断「点了没变化」。
- `perform()`：把 `Action` 翻译成点击。现有 `resource/pipeline/story_demo.json` 里已有对应的点击节点（商店三格、造物选择、事件选项、关闭弹窗、完成调查等），可复用其坐标。
- 地图格子定位：用 `tools/recognize_map_tiles.py` 识别截图，再对照 `resource/map_data/maps.json` 的行列。实机截图需要缩放到格子宽约 208 像素，这一步没有测试过。

这些都还没有做，所以现在不能直接在 MFAAvalonia 里选择「自动走地图」任务。
