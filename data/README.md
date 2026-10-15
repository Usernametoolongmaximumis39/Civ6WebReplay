# 本地开发资料

本目录位于仓库根目录，与 `Civ6WebReplay/` 并列，不参与正常复盘运行。迁移前已受 Git 管理的原始数据和工具继续保留版本管理；本地审计报告、历史备份及原先忽略的辅助工具仍不纳入 Git。发布应用时使用 `Civ6WebReplay/`。

- `gamedb/`：BBG/CCB 完整玩法库、本地化库、标签、MOD 源码、采集记录、新增内容审计，以及原版构建清单。
- `shared/`：模组对比与图标构建审计。
- `ui/`：翻译来源、缺失英文清单和核对记录。
- `docs/`：开发说明和历次机制核查资料。
- `tools/`：构建、审计、素材处理工具。`tool_paths.py` 将运行产物定位到 `Civ6WebReplay/`，将开发资料定位到本目录。
- `backups/`、`retired/`：历史备份和停用入口的源码归档。

运行所需的 `gamedb.sqlite`、各规则集 `adjacency.json`、`tileyields.json`、`rule-text.json`、版本用 `capture.json`，以及名称、总督、颜色和翻译数据仍位于 `Civ6WebReplay/data/`。归档目录复制保留采集记录以便独立核查；记录中的历史路径和文件清单是来源证据，不表示所有文件仍放在同一目录。

旧数据库采集与回档入口已移除，等待重做。`tools/capture_database.py` 和 `tools/capture_bbg.py` 的命令行入口已停用，`retired/capture_database.bat.disabled` 不可双击执行。保留旧实现和测试仅为查阅历史行为。

开发工具示例（从仓库根目录执行）：

```powershell
python -B data/tools/audit_mod_additions.py --help
python -B data/tools/build_rule_text.py --help
```

构建工具可能更新正式运行资源；测试时必须显式指定 `test/.artifacts/` 下的输出目录，或通过测试夹具替换输出路径。测试约定见根目录 `AGENTS.md` 和 `test/README.md`。
