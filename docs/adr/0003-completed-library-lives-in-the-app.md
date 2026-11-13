# The Completed Library lives in the app, not in a spreadsheet

The finished-games journal began as an Excel workbook that the app imported. Keeping the workbook and the app in step meant two places to edit the same game and rules about which one won, so schema v18 removed the import: games are added and edited only in the app, and imported games keep their data but are edited like any other. Each game is keyed by its normalized title plus the user's platform, so adding a game that is already there updates it instead of making a duplicate.
