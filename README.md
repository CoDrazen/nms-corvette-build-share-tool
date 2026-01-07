-------------------
TESTING & FEEDBACK
-------------------

This tool is currently in a TESTING phase.

It has been tested on:
- Windows 11
- Steam version of No Man’s Sky

Feedback from users with other save formats is especially valuable
(the app runs on Windows, but save formats may differ):
- GOG
- Microsoft Store
- PlayStation save imports
- Switch save imports

If you test this tool, please report:
- Your save format (Steam / GOG / Microsoft / PS / Switch)
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

A portable desktop tool for exporting and importing Corvette base builds
in No Man’s Sky.

This application allows you to:

- Export a Corvette’s Objects[] into a shareable build JSON (wrapper format)
- Import a build into another Corvette (full replace of Objects[])
- Automatically back up the entire save folder before any import write
- Run fully portable (no system-wide Python install required)


------------
REQUIREMENTS
------------

- Windows 10 / 11
- A valid No Man’s Sky save folder containing save*.hg files
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


---------
SLOT MAP
---------

No Man’s Sky stores each slot as a pair (Autosave + Restore Point):

Slot 1: save.hg  + save2.hg

Slot 2: save3.hg + save4.hg

Slot 3: save5.hg + save6.hg

...


------------
HOW IT WORKS
------------

EXPORT:
- Select a No Man’s Sky save folder
- Select a Save Slot (Slot 1, Slot 2, etc.)
- The tool converts the selected slot to JSON using libNOM
  (by default it converts the slot’s Restore Point file:
   save2.hg, save4.hg, save6.hg…)
- Select a Corvette from the list (must NOT be your active ship)
- Export its Objects[] into a build JSON file

IMPORT:
- Select a target No Man’s Sky save folder
- Select a Save Slot to import into
- Convert + load the Corvettes from that slot
- Select a target Corvette (must NOT be your active ship)
- Choose a previously exported build JSON
- The tool replaces the Corvette’s Objects[] and writes both slot files back

Safety & compatibility:
- Both files belonging to the selected slot are updated
  (Autosave + Restore Point)
- Matching metadata files (mf_save*.hg) are written as well
- A full backup of the save folder is created automatically before import


-----------------
BUILD FILE FORMAT
-----------------

Exported builds are saved as a wrapper JSON object containing metadata plus
the objects list:

- format:  NMS-CorvetteBuild
- version: 1
- name:    (your build name)
- author:  (optional)
- created_utc: timestamp
- objects: the Corvette Objects[] list

Import accepts:
- Wrapper builds with "objects": [...]
- A raw JSON list representing Objects[] directly
- Wrapper builds with "Objects": [...] (legacy/alternate format)


-------------
WORKSPACE FILES
-------------

The tool creates a workspace folder next to your save folder:

NMS_CorvetteTool/

- Backups/   (created automatically before import)
- Builds/    (default location for exported build files)
- Work/      (temporary conversion files)


----------------------
IMPORTANT SAFETY NOTES
----------------------

- ALWAYS close No Man’s Sky before exporting or importing
- DO NOT export/import into your currently active Corvette
- Use a dummy or disposable Corvette when testing
  - ENSURE you have unlocked the required Corvette parts in-game;
    otherwise, sections of the imported build may appear invisible or glitched
  - For best results, use Creative Mode or verify part ownership at a
    Corvette Workshop before importing complex designs
- Create a simple Corvette to be replaced before importing a build
- Backups are created automatically, but caution is still advised
- This tool modifies save files. Use at your own risk.


---------------
ACKNOWLEDGMENTS
---------------

This tool was inspired by the original Corvette export/import research by:

Weenzo (T-rash_raccoon)
"I managed to export and import a Corvette build"
https://www.reddit.com/r/NoMansSkyTheGame/comments/1npis7l

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
