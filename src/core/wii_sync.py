"""
Da de alta Wii (WiiWare + discos .rvz) en
Data/TamperMonkeyRetroachievements.json cruzando el .dat de
RetroAchievements (UGA_RA_DATs) contra el item de archive.org
'RetroAchievementsWii'. Ver dat_archive_sync.py para el detalle del
matching (por MD5, no por nombre).
"""

from .dat_archive_sync import DatArchiveSync

DAT_URL = (
    "https://raw.githubusercontent.com/UltraGodAzgorath/UGA_RA_DATs/main/DATs/"
    "RetroAchievements%20(No%20Subfolders)/RA%20-%20Nintendo%20Wii.dat"
)
ARCHIVE_ITEM = "RetroAchievementsWii"
MISSING_FILE = "Data/wii_missing_sources.txt"


class WiiSync(DatArchiveSync):
    def __init__(self):
        super().__init__(
            dat_url=DAT_URL,
            archive_item=ARCHIVE_ITEM,
            console_folder="Wii",
            extensions=(".rvz", ".wad", ".iso"),
            missing_file=MISSING_FILE,
        )


if __name__ == "__main__":
    WiiSync().run()
