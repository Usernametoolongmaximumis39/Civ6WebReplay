# Civ6 WebReplay

[简体中文](README.md) | English

> **AI-generated translation:** This English user guide was generated from the Chinese guide. Game and mod names follow the source data where available.

Civ6 WebReplay is a browser-based replay viewer for *Civilization VI*. Load a group of game saves and move through turns to inspect the map, cities, units, and civilization statistics.

Current version: **v0.44**. Windows is recommended, with Chrome or Edge.

## What's new in v0.44

- Technology and civic panels show saved research investment and costs adjusted for the ruleset, game speed, and world era. Unconfirmed costs remain unknown.
- A new Great People panel shows current recruitment offers, required points, and each civilization's accumulated points and points per turn.
- City-state details show Amani assignments, with related interface and Chinese/English text updates.
- Tile yields include saved cumulative extra yields, including disaster fertility. Failed parsing is reported as missing data rather than treated as zero.
- Research cost rules and Great Person name data ship with the application; replay caches are updated for the new fields.

See [CHANGELOG.md](CHANGELOG.md) for the release history.

## What's new in v0.43

- Open a single save or drop a save file or folder to import it. Folder scanning and turn parsing now load in parallel, and you can adjust the worker count.
- City production queues show invested/required Production, including lifetime-copy unit cost increases, research-based project costs, and Military Academy, Seaport and Zulu discounts for Corps and Armies. The rules ship with the application.
- City lists show district icons in placement order and infer district discounts from saved costs. Luxury inventories include resources received from other sources. The compact data panel groups teammates and hides spectators.
- Tourism appears in culture details as an estimate, preferably calculated from the next save. The final turn explicitly falls back to the previous turn's estimate.
- Unrecognized religions receive stable numbers and available icons across turns. Gold ledger parsing now counts enacted deal items only, preventing expired-log entries from being counted twice.
- Developer data and tests now live at the repository root, leaving the application package focused on runtime files. The old database capture entry point remains retired pending a rewrite.

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
4. On the first launch, the program checks for and installs required dependencies, which requires an internet connection. It opens `http://127.0.0.1:8765/` by default. If that port is occupied, it selects an available port and opens the corresponding URL.
5. When finished, press **Ctrl+C** in the launcher window to stop the service.

Required rules and icon data are included; you do not need to build the assets. The program does not modify your game saves.

The production queue denominator is total required Production. Production-rate modifiers from policies or the World Congress affect progress per turn rather than this denominator. The city yield panel reads the city's saved total yields; it does not separately estimate effective production toward a particular unit. Districts use their locked saved costs. Special projects whose costs cannot be determined reliably, such as repairing defenses, still show `?`.

## Choose saves and review a replay

Click **Open Saves** to choose a single `.Civ6Save` file or a save folder, or drop either onto the page. A single file opens at its saved turn; folders are organized by game and turn. The path box also accepts file or folder paths. The default multiplayer autosave folder is:

```text
%USERPROFILE%\Documents\My Games\Sid Meier's Civilization VI\Saves\Multi\auto
```

Single-player saves are usually under `Saves\Single` or its `auto` subfolder. Opening a folder through the path box, folder tree, or **Browse…** scans its immediate save files, and refreshing can find new saves. **Choose a folder…** and drag-and-drop also read nested folders and import session copies; import again to pick up newly added saves. If OneDrive or another setting redirects your Documents folder, choose the actual save location.

Select a replay and use the turn controls to move between turns. Click a map tile to see details, then use the **Info**, **Yields**, **Districts**, and **Units** tabs to change the detail view. Open **Compare** to compare civilizations on a separate page. Click **Refresh Saves** after adding saves.

A replay can show only turns present in the available saves. To preserve more turns, increase the autosave frequency in the game and keep enough autosaves.

Unrecognized religions appear as “Unknown Religion 1”, “Unknown Religion 2”, and so on. Each borrows a religion icon unused in the latest save's complete catalog of founded religions. Its number and icon remain consistent across turns, civilization details, city details, and the map, and it appears only once founded. If no unused religion icons remain, the generic Faith icon is used.

## Language

The language menu is in the top bar. **Auto** uses the first supported language in your browser's language preference list; if neither Chinese nor English is listed, the interface defaults to English. You can select **中文** or **English** manually. The choice is saved locally and also applies to the separate comparison page and shared visitor page.

English game names and descriptions are looked up within the selected ruleset. When a mod has no English text for an entry, the viewer does not substitute a base-game description. Custom player names and other user-entered text remain as entered.

## Base game, BBG, and CCB

The viewer selects a ruleset from the mod information in each save. It does not substitute another ruleset when data is missing. Click the question mark beside a balance mod at the top of the page to see the database and save versions.

BBG and CCB core mods are identified separately from their civilization expansions. Map packs, multiplayer helpers, and compatibility patches are not treated as core mods. Beta (including BETA and translated test labels) and WIP development builds can be shown in the version hint; the core mod and expansion can use different channels. Identification supports MOD IDs that have changed across updates. If the save does not contain reliable channel evidence, the channel remains unknown rather than inheriting the channel or version of the currently installed database snapshot. Capture records both numeric version fields found in the mod list.

Policy and ability descriptions, unique-content icons, and colors are selected for the relevant ruleset. Not every additional mod is supported for replay calculations. If an effect or save state is unsupported, the interface reports missing or unavailable data.

**Calculated yield** on a tile means that some conditions are not covered. Disaster bonus fertility is read from saved cumulative extra plot yields. City-level multipliers, trade routes, housing, power, and tourism are not included in tile yield totals. District adjacency is not the district's complete set of benefits.

The following are currently unsupported:

- Secret Societies and Monopolies and Corporations game modes.
- Mods whose title contains “Secret Society,” CCB's “Mandate of Heaven,” or “Echoes of Time.”
- Team PVP mods that rewrite rules, except for recognized interface helper components.

## Rules databases

The application uses the bundled base-game, BBG, and CCB runtime snapshots. The old capture and rollback entry points have been removed pending a rewrite. Use the snapshots included with the complete application package.

## Share a replay

Click **Share** at the top of the page, enable sharing as prompted, and copy the link for other people. The default sharing port starts at **8766**; the main page uses **8765** by default and selects another port if needed.

Other devices must be able to reach your computer through a LAN, virtual LAN, or configured public endpoint. Public access may require port forwarding and firewall rules. A copied link alone does not guarantee that the network path is reachable. The sharing service has no sign-in, so only share it with people you intend to let view the replay.

While sharing is active, save-folder selection and refresh are locked. They become available again after sharing stops. Closing the program also stops sharing.

## Troubleshooting

**The launcher says Python cannot be found.**

Reinstall Python with **Add Python to PATH** enabled, or check that `python --version` works in a terminal. Then reopen the launcher.

**No replay appears in the page.**

Check that the selected folder directly contains `.Civ6Save` files and click **Refresh Saves**. A single-turn save cannot show a complete history.

**Want to choose the main page port?**

Open a terminal in the Civ6WebReplay folder and run the command below. If the specified port is occupied, the launcher selects an available port:

```powershell
.\start.bat --port 9000
```

You can also specify a save folder at launch:

```powershell
.\start.bat --save-dir "D:\Civ6Saves"
```

**The first load takes a long time.**

The initial scan reads saves using multiple threads, and background workers parse turns in multiple processes. The default concurrency is half the CPU's logical thread count, rounded down, with a minimum of 1 worker. For example, an 8-core, 16-thread CPU uses 8 workers by default. Each turn becomes available as soon as it finishes. Parsed results are stored in `cache\replay.sqlite`, so later loads are usually faster. You can delete this cache after closing the program; the saves will be parsed again the next time.

Use `.\start.bat --load-workers 2` or the `CIV6_REPLAY_WORKERS` environment variable to adjust concurrency (1–16). Set it to `1` for sequential loading. More workers use more CPU and memory.

**A map value or tile yield is unavailable.**

Read the message shown in the interface and check the save's game mode, mods, and database ruleset. Check that the application package contains the matching rules snapshot. The old capture feature is currently disabled. Effects that have not been implemented will still be marked as missing.

## Data and license

The program reads the game saves you choose on your computer and does not upload them to GitHub. Installing dependencies for the first run requires internet access; sharing-address detection may also contact external network services.

Project code is licensed under the [MIT License](../LICENSE). Sources and license boundaries for third-party parser code, game text, icons, and mod content are described in [Third-Party Notices](../THIRD_PARTY_NOTICES.md). This project is not affiliated with Firaxis Games or 2K.
