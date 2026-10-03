# 忘却篇地图资料与格子标记

## 批量获取第 1–9 章地图

在项目根目录运行：

```powershell
python tools/fetch_huiji_maps.py --out resource/reference_maps
python tools/fetch_huiji_maps.py --out resource/reference_maps --download
```

第一条通过灰机 Wiki 的 MediaWiki API 获取图片目录，生成 `huiji_maps_1-9.json`。第二条下载原图至 `images` 目录，并逐张用 API 给出的 SHA-1 校验。重复运行会跳过校验通过的文件；失败会写入清单的 `download_error`。当前从 API 找到 88 张地图：第 1–9 章依次为 8、12、10、12、10、10、12、10、4 张。该数量是维基当前收录的地图文件数，并非全部剧情关卡数。若 HTTPS 图片地址返回 567，脚本会尝试同地址的 HTTP 版本，并且只保存与 HTTPS API 的 SHA-1 一致的图片。

API 查询使用 `action=query&list=allimages&aiprefix=忘却篇&aisort=name&ailimit=500&aiprop=url|size|timestamp|sha1`，并处理 `continue` 分页；按 `忘却篇<章>-<关>_map.jpg/png` 筛选。更多字段可参考 [MediaWiki Allimages](https://www.mediawiki.org/wiki/API:Allimages) 和 [Imageinfo](https://www.mediawiki.org/wiki/API:Imageinfo)。

资料来源：灰机维基 `huiji-events.json`（本地缓存，CC BY-NC-SA，2026-10-03 获取），以及 [8-2 关卡页面](https://morimens.huijiwiki.com/wiki/终末交响曲-02) 和[8-2 剧情事件](https://morimens.huijiwiki.com/wiki/终末交响曲-02·剧情)。

## 实机可确认的地图状态

| 外观 | 标记 | 当前处理 |
| --- | --- | --- |
| 绿色描边六角格 | 候选未走格 | 优先列为下一步目标；点击后必须重新截图验证 |
| 青蓝描边六角格 | 已走格 | 在有绿色候选时不选 |
| 人物头像所在格 | 当前格 | 不重复点击 |
| 暗灰色且无绿色描边 | 当前不可达或未知 | 不根据图标盲点 |
| 锁图标 | 锁门 | 仅在实机确认持有「锈蚀钥匙」且格子可达时尝试 |

这些颜色标记来自 1600×900 模拟器截图验证，不代表所有章节和画质设置。`tools/preprocess_map.py` 只读取截图，输出绿色候选格坐标与事件资料，不会点击模拟器。

## 8-2 已核对事件

| 事件 | 已知选项与结果 | 预处理 |
| --- | --- | --- |
| 监察点 | 离开；诈降：探索完区域后传送到羁押点，获得 2 张随机症状；闯入：同样传送但失去生命 | 优先记录传送和损失，不能把「诈降」当普通收益 |
| 入学仪式 | 选卡及刻印分支 | 识别为卡牌选择，等待后续画面确认 |
| 羁押点 | 监察点后的传送目的地 | 传送后重建当前格和邻格 |

维基关卡页面使用地图文件名 `忘却篇8-2_map.jpg`。已通过维基 API 确认资源为 3508×1974，页面为[地图文件](https://morimens.huijiwiki.com/wiki/文件:忘却篇8-2_map.jpg)。下载时若 HTTPS CDN 返回 567，可使用脚本的 HTTP 回退并校验 SHA-1。

后续路线规则：先读取绿色候选格；按截图重新判定可达；锁门需确认钥匙；进入事件后读取标题和选项，将传送、生命损失、症状等代价显式记录；每步返回地图重新识别。维基抄本是先验资料，实机画面是最终判断依据。
