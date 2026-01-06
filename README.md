-------------------
TESTING & FEEDBACK
-------------------

This tool is currently in a TESTING phase.

It has been tested on:
- Windows 11
- Steam version of No Man’s Sky

Feedback from users on other platforms is especially valuable:
- GOG
- Microsoft Store
- PlayStation save imports
- Switch save imports

If you test this tool, please report:
- Your platform (Steam / GOG / Microsoft / PS / Switch)
- Whether export worked
- Whether import worked
- Any errors or warnings shown
- Anything unexpected or unclear

You can report feedback or issues here:
https://github.com/CoDrazen/nms-corvette-build-share-tool/issues

Even a simple “works fine on my setup” is helpful.


-----------------------------
NMS Corvette Build Share Tool
-----------------------------

A portable desktop tool for exporting and importing Corvette base builds in No Man’s Sky.

This application allows you to:

- Export a Corvette’s base objects into a shareable JSON build file
- Import a build into another Corvette (full replace)
- Automatically back up save files before any modification
- Run fully portable (no system-wide Python install required)


------------
REQUIREMENTS
------------

- Windows 10 / 11
- A valid save folder containing save2.hg
- .NET Desktop Runtime (x64)

IMPORTANT:
If .NET is not installed, Windows may prompt you to install it
automatically when the tool runs (similar to libNOM / NomNom behavior).

.NET is only required to run the included libNOM tool and does not affect
the portability of this application.


----------
HOW TO RUN
----------

Option A (normal app experience, no console window):
- Double-click run.vbs

Option B (debug / see logs):
- Double-click run_debug.bat


------------
HOW IT WORKS
------------

EXPORT:
- Select a No Man’s Sky save folder
- Select a Save Slot (Slot 1, Slot 2, etc.)
- The tool converts the selected slot’s save to JSON using libNOM
- Select a Corvette from the list (must NOT be your active ship)
- Export its Objects[] into a build JSON file

IMPORT:
- Select a target No Man’s Sky save folder
- Select a Save Slot to import into
- Convert + load the Corvettes from that slot
- Select a target Corvette (must NOT be your active ship)
- Choose a previously exported build JSON
- The tool replaces the Corvette’s Objects[] and writes the save back

Safety & compatibility:
- Both files belonging to the selected slot are updated (Autosave + Restore Point)
- Matching metadata files (mf_save*.hg) are written as well
- A full backup of the save folder is created automatically before import


----------------------
IMPORTANT SAFETY NOTES
----------------------

ALWAYS close No Man’s Sky before exporting or importing
DO NOT import into your currently active Corvette
Use an empty or disposable Corvette when testing

Backups are created automatically, but caution is still advised

This tool modifies save files. Use at your own risk.


---------------
ACKNOWLEDGMENTS
---------------

This tool was inspired by the original Corvette export/import research by:

Weenzo (T-rash_raccoon)
"I managed to export and import a Corvette build"
https://www.reddit.com/r/NoMansSkyTheGame/comments/1npis7l/i_managed_to_export_and_import_a_corvette_build/

Special thanks to Weenzo for documenting the method that made this tool possible.

Also thanks to the libNOM project for save file parsing and conversion.


----------
DISCLAIMER
----------

This is a community-made tool.
Not affiliated with Hello Games.

No Man’s Sky is a trademark of Hello Games Ltd.


-------
LICENSE
-------

License: Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International
(CC BY-NC-SA 4.0).

You may use, modify, and share this tool freely for non-commercial purposes.
Commercial use is not permitted without explicit permission from the author.

If you use parts of this code, please credit:
- CoDrazen
- libNOM project
- Weenzo (research inspiration)
