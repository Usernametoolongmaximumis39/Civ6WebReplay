# Civ6 WebReplay

[简体中文](README.md) | [English (AI-generated)](README.en.md)

在浏览器中复盘《文明 VI》的存档，查看地图变化、城市与单位、文明数据、政策和技能说明，以及地块产出与区域相邻加成。支持原版、BBG 和 CCB 的独立规则数据，并提供中英文界面与自动语言识别。

## 开始使用

1. 安装 [Python 3.11 或更新版本](https://www.python.org/downloads/)，安装时勾选 **Add Python to PATH**。
2. 下载本仓库 ZIP 并解压，或使用 Git 克隆。
3. 打开 `Civ6WebReplay` 文件夹，双击 `start.bat`。
4. 浏览器打开后，点击 **打开存档**，选择单个 `.Civ6Save` 文件或存档文件夹，也可以将它们拖到页面上。

详细操作、规则数据库、共享和常见问题见 **[用户说明](Civ6WebReplay/README.md)**；英文指南见 [English user guide (AI-generated)](Civ6WebReplay/README.en.md)。

程序默认在本机运行，地址为 `http://127.0.0.1:8765/`。游戏存档保存在用户自己的电脑上；只有主动开启共享后，其他人才能通过相应网络入口查看复盘。

## 开发目录

`Civ6WebReplay/` 为应用目录；根目录 `data/` 保存本地开发资料与归档工具，`test/` 保存测试脚本及产物。测试不得在应用目录中运行或写入，具体约定见 [AGENTS.md](AGENTS.md)。根目录运行 `python -B test/run.py`。旧数据库采集入口已停用，等待重做。

## 开源许可

项目代码采用 [MIT License](LICENSE)。第三方代码、游戏及模组素材的来源与许可范围见 [第三方说明](THIRD_PARTY_NOTICES.md)。本项目与 Firaxis Games、2K 无隶属关系。
