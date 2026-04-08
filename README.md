NMS Corvette Build Share Tool
=============================

Build wrapper version: 1

A portable desktop tool for exporting and importing Corvette base builds
in No Man's Sky.


Support Boundary
----------------

Officially supported and verified:
- Windows 10 / 11
- Steam saves

Available in the UI as manual or compatibility options, but not yet officially
verified end-to-end:
- GOG
- Microsoft Store
- PlayStation save imports
- Switch save imports

Notes:
- The app can auto-detect the save platform when possible.
- If detection is unclear, you can choose the platform manually in the UI.
- If you use multiple save formats, double-check the platform before writing.


What The Tool Does
------------------

- Export a Corvette's `Objects[]` into a shareable build JSON wrapper
- Import a build into another Corvette by replacing its `Objects[]`
- Create a full backup of the selected save folder before any import write
- Run either from the source repo or as a portable single-file EXE release

This tool imports build parts, placement, and colors only.
It does not change ship class, stats, inventory, upgrades, or ownership.


Requirements
------------

- Windows 10 / 11
- A valid No Man's Sky save folder containing `save*.hg` files
- .NET Desktop Runtime (x64)

If .NET is not installed, Windows may prompt you to install it when the
tool runs. .NET is only required for the included `libNOM` tool.


How To Run
----------

Portable EXE release:
- Run `NMS Corvette Build Share Tool.exe`
- The EXE is portable and can live in any folder
- A settings file is only created if the app actually needs to save settings

Source repo:
- Double-click `run.vbs`
- Use `run_debug.bat` only if you want pairing/debug output in a console

Building the portable EXE from the repo:
- Run `build_release.ps1`
- Default output folder: `C:\NMS-App-Release`


Basic Workflow
--------------

Export:
- Choose the No Man's Sky save folder to read from
- Choose the workspace root if you do not want to use the default location
- Leave Platform on `Auto-detect` or choose it manually
- Select a slot
- Click `Convert + Load Corvettes`
- Select a Corvette that is not your active ship
- Click `Export Build`

Import:
- Choose the No Man's Sky save folder to write to
- Choose the workspace root if you do not want to use the default location
- Leave Platform on `Auto-detect` or choose it manually
- Select a slot
- Click `Convert + Load Corvettes`
- Select a target Corvette that is not your active ship
- Click `Import Build (Replace)`
- Confirm the backup and overwrite prompt


Workspace Root
--------------

By default, the app creates a workspace next to the selected save folder:

- `<save parent>\NMS_CorvetteTool\`

Inside that workspace it creates:
- `Backups\`
- `Builds\`
- `Work\Export\<save_id>\`
- `Work\Import\<save_id>\`

You can override the workspace root from the UI with `Choose Workspace Root`.
Use `Use Default` to go back to the standard location.


Slot Map
--------

No Man's Sky stores each slot as a pair:

- Slot 1: `save.hg` + `save2.hg`
- Slot 2: `save3.hg` + `save4.hg`
- Slot 3: `save5.hg` + `save6.hg`

The app converts from the restore-point file by default and writes both files
for the selected slot during import.


Build File Format
-----------------

Official exported builds use this wrapper:

- `format`: `NMS-CorvetteBuild`
- `version`: `1`
- `name`: build name
- `author`: optional
- `created_utc`: timestamp
- `objects`: the Corvette `Objects[]` list

Import rules:
- Official wrapper files must contain the expected `format` and a supported `version`
- Raw JSON `Objects[]` lists are still accepted as compatibility input
- Wrappers containing `Objects` are still accepted as compatibility input


Safety Notes
------------

- Always close No Man's Sky before exporting or importing
- Do not export from or import into your active Corvette
- Use a dummy or disposable Corvette when testing imports
- Make sure the required Corvette parts are unlocked in-game
- The app stops import if the backup cannot be completed
- This tool modifies save files. Use it carefully


Known Limitations
-----------------

- Official support is currently scoped to Windows + Steam saves
- Platform auto-detection may not succeed for every save source
- Corvette pairing is based on available save data and heuristics
- Some imported builds may not look correct if the target save lacks parts


Feedback And Issues
-------------------

Report bugs or compatibility issues here:

https://github.com/CoDrazen/nms-corvette-build-share-tool/issues

Helpful details:
- Save platform
- Windows version
- Whether export worked
- Whether import worked
- Any warnings or errors shown
- Whether the save loaded correctly in-game

Acknowledgments
---------------

This tool was inspired by Corvette export/import research by:

- Weenzo (T-rash_raccoon)
- "I managed to export and import a Corvette build"
- https://www.reddit.com/r/NoMansSkyTheGame/comments/1npis7l

Also thanks to the `libNOM` project for save parsing and conversion.


Disclaimer
----------

This is a community-made tool.
Not affiliated with Hello Games.

No Man's Sky is a trademark of Hello Games Ltd.


License
-------

License: Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International
(`CC BY-NC-SA 4.0`).

You may use, modify, and share this tool freely for non-commercial purposes.
Commercial use is not permitted without explicit permission from the author.
