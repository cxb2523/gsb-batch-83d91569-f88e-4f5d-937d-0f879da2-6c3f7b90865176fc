"""
Da de alta Nintendo GameCube en Data/TamperMonkeyRetroachievements.json
cruzando el .dat de RetroAchievements (UGA_RA_DATs) contra el item de
archive.org 'RetroAchievementsGameCube'. Ver dat_archive_sync.py para el
detalle del matching (por MD5, no por nombre).
"""

from .dat_archive_sync import DatArchiveSync

DAT_URL = (
    "https://raw.githubusercontent.com/UltraGodAzgorath/UGA_RA_DATs/main/DATs/"
    "RetroAchievements%20(No%20Subfolders)/RA%20-%20Nintendo%20GameCube.dat"
)
ARCHIVE_ITEM = "RetroAchievementsGameCube"
MISSING_FILE = "Data/gamecube_missing_sources.txt"


class GameCubeSync(DatArchiveSync):
    def __init__(self):
        super().__init__(
            dat_url=DAT_URL,
            archive_item=ARCHIVE_ITEM,
            console_folder="GameCube",
            extensions=(".rvz",),
            missing_file=MISSING_FILE,
        )


if __name__ == "__main__":
    GameCubeSync().run()
