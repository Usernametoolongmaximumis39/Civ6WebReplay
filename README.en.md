# Civ6 WebReplay

[简体中文](README.md) | English

> **AI-generated:** This English overview was generated from the Chinese project documentation.

Civ6 WebReplay is a browser-based replay viewer for *Civilization VI*. Review map changes, cities, units, civilization statistics, policy and ability descriptions, tile yields, and district adjacency across turns. It includes separate rules data for the base game, BBG, and CCB, plus a Chinese and English interface with automatic language detection.

## Quick start

1. Install [Python 3.11 or later](https://www.python.org/downloads/) and enable **Add Python to PATH** during setup.
2. Download and extract this repository ZIP, or clone it with Git.
3. Open the **Civ6WebReplay** folder and double-click **start.bat**.
4. In the browser, click **Save Folder** and choose the folder containing your `.Civ6Save` files.

See the full [English user guide](Civ6WebReplay/README.en.md) (AI-generated) or the [Chinese user guide](Civ6WebReplay/README.md) for replay controls, database capture and rollback, sharing, and troubleshooting.

The program runs locally by default at `http://127.0.0.1:8765/`. Your saves stay on your computer. Other people can view a replay only after you explicitly enable sharing and provide them a reachable link.

## Open source

Project code is licensed under the [MIT License](LICENSE). Sources and license boundaries for third-party code, game data, and mod content are described in [Third-Party Notices](THIRD_PARTY_NOTICES.md). This project is not affiliated with Firaxis Games or 2K.
