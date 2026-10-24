# 版本记录 / Release history

## v0.44 — 2026-10-24

- 科技与市政显示存档中的已投入进度，以及按规则集、游戏速度和世界时代计算的所需点数；无法确认的造价显示未知。
- 新增伟人信息面板，展示当前可招募伟人、所需点数及各文明的伟人点数与每回合产出。
- 城邦信息显示阿玛妮派驻情况，并完善相关界面与中英文文本。
- 地块产出纳入存档保存的累计额外产出（含灾害肥力）；解析失败时明确提示缺失，不将其视为零。
- 随应用附带科研造价规则与伟人名称数据，启动时检查必需文件；更新复盘缓存以适配新字段，并统一伟人点数字典键以保持并行加载与缓存往返一致。

- Technology and civic panels show saved research investment and costs adjusted for the ruleset, game speed, and world era. Unconfirmed costs remain unknown.
- A new Great People panel shows current recruitment offers, required points, and each civilization's accumulated points and points per turn.
- City-state details show Amani assignments, with related interface and Chinese/English text updates.
- Tile yields include saved cumulative extra yields, including disaster fertility. Failed parsing is reported as missing data rather than treated as zero.
- Research cost rules and Great Person name data ship with the application; replay caches are updated for the new fields.

### 发布核验 / Release verification

- 已检查所有可发布应用文件均纳入 Git，新增科研规则、伟人名称数据与三个解析模块均包含在发布内容中。
- 从 Git 暂存区独立导出副本，验证运行 JSON、启动文件检查、规则加载及首页和 API；无需本地开发资料目录。
- 科研进度、伟人、阿玛妮、地图产出及产出面板共五项 JavaScript 检查通过。
- 修复伟人点数字典的 JSON 往返一致性，并验证真实存档的串行／并行加载一致。
- 完整 Python 回归：722 通过、9 跳过、2 失败；两项失败均为已停用采集工具在 Windows 下重命名备份目录时的 `WinError 5`，未修改或恢复该工具。此前失败项及新功能定向复跑共 36 项通过。
- 测试脚本与测试产物按项目约定保留在本地 `test/`；已停用的数据库采集工具未恢复。

## v0.43

存档拖拽与并行加载、城市生产造价、区域显示及宗教编号改进。详见中英文用户指南中的 v0.43 更新记录。
