# 游戏客户端地图数据（来自 Z769018860/qdby_chinese）

提交：`2d0be1a5b614d29d7f8ecb08fafbac2b60c997c5`；导出时间 2026-10-12/13（Steam 客户端运行时已加载的 Lua 配置，只读导出，由仓库维护者提供）。

由 `python tools/import_client_maps.py <qdby_chinese 路径>` 生成，原始表在该仓库 `data/morimens/local-config/`，说明见那里的 README。

文件：
- `node_types.json`：80 种节点类型 → 本项目的格子类型（`ours`）与客户端标志。
- `nodes.json`：节点 id → [类型 id, 战斗配置 id]。
- `maps.json`：每张地图的 8 行 × 13 列格子（0=墙/虚无，null=空地，整数=节点 id，列表=该格有多个随机变体）。
- `stages.json`：关卡 id → 名称/分类/等级/地图 id/线性节点序列。
- `train.json`：记忆回廊「疾驰的欢愉专列」路线。
- 上一级 `maps_client.json`：转换成规划器使用的蜂窝格点（island/row/col）。

坐标：行 y=1..8（y=8 在最下方），列 x=1..13，奇数行向右错半格；格点 col = 2*x + (y 为奇数)，row = -y。配置里没有的格子是空地，节点「虚无」是墙。该规律在 8-2 上与截图识别、实机结果逐格核对过。
