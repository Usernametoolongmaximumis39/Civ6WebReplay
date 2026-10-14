# Civ6 WebReplay

[简体中文](README.md) | English

> **AI-generated translation:** This English user guide was generated from the Chinese guide. Game and mod names follow the source data where available.

Civ6 WebReplay is a browser-based replay viewer for *Civilization VI*. Load a group of game saves and move through turns to inspect the map, cities, units, and civilization statistics.

Current version: **v0.42**. Windows is recommended, with Chrome or Edge.

## What's new in v0.42

- Chinese and English interface, with automatic browser-language detection or a manual language menu. The selection is saved on this computer.
- English game text is selected by ruleset. BBG and CCB core mods, civilization expansions, and Beta or WIP channels are identified separately when the save or installed files provide evidence.
- Updated CCB 1.8 database capture. Missing Lua scripts are recorded as missing; capture does not fabricate them.

## What you can inspect

- Turn-by-turn map: cities, districts, buildings, improvements, resources, roads, rivers, units, and fog of war.
- City and unit details: population, production queue, completed buildings, pillage status, health, governors, and unit promotions.
- Civilization statistics and a separate comparison page: science, civics, economy, military, culture, diplomacy, and more.
- Civilization and leader abilities, policy names, and descriptions. Click a portrait or policy title to expand details.
- Six tile yields and their sources, plus district adjacency. Base-game, BBG, and CCB rules are displayed independently.
- Map layers, zoom and layout preferences, the continent lens, and highlighted luxury resources.
- Replay sharing with people who can reach your computer over the network, after you explicitly enable sharing.

## Install and start

1. Install [Python 3.11 or later](https://www.python.org/downloads/). Enable **Add Python to PATH** during setup.
2. On GitHub, choose **Code → Download ZIP** and extract it to a local folder.
3. Open the extracted **Civ6WebReplay** folder and double-click **start.bat**.
4. On the first launch, the program checks for and installs required dependencies, which requires an internet connection. It then opens `http://127.0.0.1:8765/` in your browser.
5. When finished, press **Ctrl+C** in the launcher window to stop the service.

Required rules and icon data are included; you do not need to build the assets. The program does not modify your game saves.

## Choose saves and review a replay

At the top of the page, click **Save Folder** and choose the folder containing `.Civ6Save` files. The default multiplayer autosave folder is:

```text
%USERPROFILE%\Documents\My Games\Sid Meier's Civilization VI\Saves\Multi\auto
```

Single-player saves are usually under `Saves\Single` or its `auto` subfolder. Choose the folder that directly contains the save files; the program does not scan all subfolders recursively. If OneDrive or another setting redirects your Documents folder, choose the actual save folder in the interface.

Select a replay and use the turn controls to move between turns. Click a map tile to see details, then use the **Info**, **Yields**, **Districts**, and **Units** tabs to change the detail view. Open **Compare** to compare civilizations on a separate page. Click **Refresh Saves** after adding saves.

A replay can show only turns present in the available saves. To preserve more turns, increase the autosave frequency in the game and keep enough autosaves.

## Language

The language menu is in the top bar. **Auto** uses the first supported language in your browser's language preference list; if neither Chinese nor English is listed, the interface defaults to English. You can select **中文** or **English** manually. The choice is saved locally and also applies to the separate comparison page and shared visitor page.

English game names and descriptions are looked up within the selected ruleset. When a mod has no English text for an entry, the viewer does not substitute a base-game description. Custom player names and other user-entered text remain as entered.

## Base game, BBG, and CCB

The viewer selects a ruleset from the mod information in each save. It does not substitute another ruleset when data is missing. Click the question mark beside a balance mod at the top of the page to see the database and save versions.

BBG and CCB core mods are identified separately from their civilization expansions. Map packs, multiplayer helpers, and compatibility patches are not treated as core mods. Beta (including BETA and translated test labels) and WIP development builds can be shown in the version hint; the core mod and expansion can use different channels. Identification supports MOD IDs that have changed across updates. If the save does not contain reliable channel evidence, the channel remains unknown rather than inheriting the channel or version of the currently installed database snapshot. Capture records both numeric version fields found in the mod list.

Policy and ability descriptions, unique-content icons, and colors are selected for the relevant ruleset. Not every additional mod is supported for replay calculations. If an effect or save state is unsupported, the interface reports missing or unavailable data.

**Calculated yield** on a tile means that some conditions are not covered. Disaster bonus fertility, city-level multipliers, trade routes, housing, power, and tourism are not included in tile yield totals. District adjacency is not the district's complete set of benefits.

The following are currently unsupported:

- Secret Societies and Monopolies and Corporations game modes.
- Mods whose title contains “Secret Society,” CCB's “Mandate of Heaven,” or “Echoes of Time.”
- Team PVP mods that rewrite rules, except for recognized interface helper components.

## Capture or update BBG / CCB databases

The included data is usually ready to use. Capture a database only when you need data matching a newer BBG or CCB rules version:

1. Close Civ6 WebReplay if it is running.
2. Double-click **capture_database.bat**, choose **BBG** or **CCB**, then choose to capture new data.
3. Follow the prompts to enable the target core mod and recognized companion mods, then start a single-player game. Do not mix BBG and CCB, and disable extra rules mods and unsupported modes.
4. After the tool says it is ready, return to the game and save once more. Keep the current game session open.
5. Return to the capture window and enter **Y**. Check the detected save path and follow the remaining prompts.
6. After a successful capture, restart Civ6 WebReplay.

Capture saves the active rules, localization text, and mod game scripts. It updates policy and ability text, tile yields, district adjacency, and governor data. Unsupported rules or Lua effects do not become calculable just because a new database was captured.

If the game installation, cache, or save folder cannot be detected, the tool asks for the actual path. It refuses to switch data when the save is too old, the mods do not match, or the database changed during capture.

New names such as “CCB正式版1.8” are supported. If the mod list references a Lua script that is not present in the installation, capture warns about it and records the missing file, then saves the database that actually took effect. It does not create a placeholder script or mark the missing script as captured.

### Back up and roll back

Before each capture, the tool backs up the existing data. Backups are stored under `data\backups\bbg` or `data\backups\ccb`. Run **capture_database.bat** again, choose the ruleset, and select a backup by date and version to restore or delete it.

Rollback also backs up the current data. Restart the replay viewer after a successful capture or rollback. Game saves are never overwritten.

## Share a replay

Click **Share** at the top of the page, enable sharing as prompted, and copy the link for other people. The default sharing port starts at **8766**; the main page continues to use **8765**.

Other devices must be able to reach your computer through a LAN, virtual LAN, or configured public endpoint. Public access may require port forwarding and firewall rules. A copied link alone does not guarantee that the network path is reachable. The sharing service has no sign-in, so only share it with people you intend to let view the replay.

While sharing is active, save-folder selection and refresh are locked. They become available again after sharing stops. Closing the program also stops sharing.

## Troubleshooting

**The launcher says Python cannot be found.**

Reinstall Python with **Add Python to PATH** enabled, or check that `python --version` works in a terminal. Then reopen the launcher.

**No replay appears in the page.**

Check that the selected folder directly contains `.Civ6Save` files and click **Refresh Saves**. A single-turn save cannot show a complete history.

**The default port is already in use.**

Open a terminal in the Civ6WebReplay folder and run:

```powershell
.\start.bat --port 9000
```

You can also specify a save folder at launch:

```powershell
.\start.bat --save-dir "D:\Civ6Saves"
```

**The first load takes a long time.**

Many saves must be parsed one by one. Parsed results are stored in `cache\replay.sqlite`, so later loads are usually faster. You can delete this cache after closing the program; the saves will be parsed again the next time.

**A map value or tile yield is unavailable.**

Read the message shown in the interface and check the save's game mode, mods, and database ruleset. For BBG or CCB, capture a matching database using the steps above. Effects that have not been implemented will still be marked as missing.

## Data and license

The program reads the game saves you choose on your computer and does not upload them to GitHub. Installing dependencies for the first run requires internet access; sharing-address detection may also contact external network services.

Project code is licensed under the [MIT License](../LICENSE). Sources and license boundaries for third-party parser code, game text, icons, and mod content are described in [Third-Party Notices](../THIRD_PARTY_NOTICES.md). This project is not affiliated with Firaxis Games or 2K.
