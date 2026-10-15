# 项目目录与测试约定

- `Civ6WebReplay/` 只放可发布的应用代码、网页、素材和运行必需的数据。
- 根目录 `data/` 保存开发资料：原始游戏数据库、MOD 源码归档、审计报告、开发文档及构建工具。保持原版、BBG、CCB 分离。
- 根目录 `test/` 保存所有测试脚本、测试夹具和测试工作目录。测试读取应用源码与运行数据时应只读。
- **不得在 `Civ6WebReplay/` 中开展测试或写入测试内容。** 测试服务的工作目录、临时存档、SQLite 缓存、日志、截图、浏览器产物、pytest 缓存和实验脚本均放到 `test/`，临时产物优先使用 `test/.artifacts/` 或 `test/_scratch/`。
- 测试 Python 进程设置 `PYTHONDONTWRITEBYTECODE=1`（或使用 `python -B`），防止在应用源码中生成 `__pycache__`。测试服务通过 `CIV6_REPLAY_CACHE` 使用独立缓存，不得使用用户的正式复盘缓存。
- 从仓库根目录运行 `python -B test/run.py`；指定用例可使用 `python -B test/run.py test/test_state.py`。JavaScript 用例从 `test/` 运行 `node test_xxx.js`，共用 `test/paths.js` 管理路径。
- 旧数据库采集功能已经停用。`data/tools/capture_database.py`、`capture_bbg.py`、`database_maintenance.py` 及 `data/retired/` 仅为重做时的参考；不得恢复采集入口或让应用启动时调用它们，除非用户明确要求重做。
- 更新资料布局时同时修正工具、测试与文档引用。移动已有数据前核对路径和归属，禁止用删除替代归档。

## 数学公式

行内公式使用 `\( ... \)`，块级公式使用 `\[ ... \]`，不要使用单美元定界符。
