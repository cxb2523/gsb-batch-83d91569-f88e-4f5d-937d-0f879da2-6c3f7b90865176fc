from __future__ import annotations

import logging
from pathlib import Path

import pytest

from ehentai_crawler.errors import SettingsError
from ehentai_crawler.settings import Settings, load_settings

REPO = Path(__file__).resolve().parents[1]

#: The setting.ini shipped by the 2019 version, verbatim (placeholders included).
SETTING_INI_2019 = """
[Mode]

EX_MODE = True
HEADLESS = False

[HentaiUrl]

EHENTAI_INDEX = https://e-hentai.org/
EHENTAI_LIST = https://e-hentai.org/?page=
EHENTAI_GALLERY = https://e-hentai.org/g/

EXHENTAI_INDEX = https://exhentai.org/
EXHENTAI_LIST = https://exhentai.org/?page=
EXHENTAI_GALLERY = https://exhentai.org/g/

[ExHentaiAccess]

IPB_MEMBER_ID = <YOUR_MEMBER_ID>
IPB_PASS_HASH = <YOUR_PASS_HASH>


[Parallel]

NUMBER_OF_THREAD = 24

[ImageFolder]

IMAGE_FOLDER_PATH = img
"""


def write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def test_defaults_match_the_2019_setting_ini(tmp_path):
    old = load_settings(write(tmp_path / "old.ini", SETTING_INI_2019), env={})
    assert old == Settings()
    assert (old.ex_mode, old.headless, old.number_of_thread) == (True, False, 24)
    assert (old.image_folder_path, old.database_path) == (Path("img"), Path("list.db"))
    assert old.index_url == "https://exhentai.org/" and old.gallery_url == "https://exhentai.org/g/"


def test_2019_placeholders_count_as_no_cookies(tmp_path):
    old = load_settings(write(tmp_path / "old.ini", SETTING_INI_2019), env={})
    assert old.ipb_member_id == "" and not old.has_login_cookies


def test_2019_list_url_keys_are_ignored_quietly(tmp_path, caplog):
    with caplog.at_level(logging.INFO):
        load_settings(write(tmp_path / "old.ini", SETTING_INI_2019), env={})
    assert not [r for r in caplog.records if r.levelno >= logging.INFO]


def test_example_file_matches_the_defaults():
    assert load_settings(REPO / "setting.example.ini", env={}) == Settings()


def test_missing_default_file_is_fine():
    assert load_settings(env={}) == Settings()  # the tests run in an empty folder


def test_missing_explicit_file_is_an_error(tmp_path):
    with pytest.raises(SettingsError, match="config file not found"):
        load_settings(tmp_path / "nope.ini", env={})
    with pytest.raises(SettingsError, match="config file not found"):
        load_settings(env={"EHENTAI_CONFIG": str(tmp_path / "nope.ini")})


def test_setting_ini_in_current_folder_is_read():
    write(Path("setting.ini"), "[Parallel]\nNUMBER_OF_THREAD = 3\n")
    assert load_settings(env={}).number_of_thread == 3


def test_precedence_defaults_ini_env_cli(tmp_path):
    ini = write(tmp_path / "s.ini", "[Parallel]\nNUMBER_OF_THREAD = 3\n[Politeness]\nREQUEST_DELAY = 2.5\n")
    env = {"EHENTAI_NUMBER_OF_THREAD": "4", "EHENTAI_EX_MODE": "no"}
    resolved = load_settings(ini, env=env, overrides={"number_of_thread": 5, "timeout": None})

    assert resolved.request_delay == 2.5  # from the file
    assert resolved.ex_mode is False  # from the environment
    assert resolved.number_of_thread == 5  # the flag beats both
    assert resolved.timeout == Settings().timeout  # None means "flag not given"


def test_cookies_from_environment():
    resolved = load_settings(env={"EHENTAI_IPB_MEMBER_ID": "1", "EHENTAI_IPB_PASS_HASH": "x"})
    assert resolved.has_login_cookies


def test_cookies_never_show_in_repr():
    resolved = Settings(ipb_member_id="member-secret", ipb_pass_hash="hash-secret")
    assert "secret" not in repr(resolved)


def test_choices_are_case_insensitive():
    resolved = load_settings(env={"EHENTAI_FETCHER": "Browser", "EHENTAI_LOG_LEVEL": "debug"})
    assert (resolved.fetcher, resolved.log_level) == ("browser", "DEBUG")


def test_bad_value_names_its_source(tmp_path):
    ini = write(tmp_path / "s.ini", "[Parallel]\nNUMBER_OF_THREAD = many\n")
    with pytest.raises(SettingsError, match=r"\[Parallel\] NUMBER_OF_THREAD is invalid"):
        load_settings(ini, env={})
    with pytest.raises(SettingsError, match="EHENTAI_EX_MODE is invalid: expected yes/no"):
        load_settings(env={"EHENTAI_EX_MODE": "maybe"})


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"number_of_thread": 0}, "at least 1"),
        ({"request_delay": -1}, "negative"),
        ({"ehentai_index": "e-hentai.org"}, "EHENTAI_INDEX is not a URL"),
    ],
)
def test_invalid_values_are_rejected(override, message):
    with pytest.raises(SettingsError, match=message):
        load_settings(env={}, overrides=override)


def test_unknown_key_is_reported(tmp_path, caplog):
    ini = write(tmp_path / "s.ini", "[Parallel]\nNUMBER_OF_THREADS = 3\n")
    load_settings(ini, env={})
    assert "unknown setting [Parallel] NUMBER_OF_THREADS" in caplog.text


def test_login_cookies_only_go_to_exhentai():
    jar = Settings(ipb_member_id="1", ipb_pass_hash="x").cookies_by_host()
    assert jar["e-hentai.org"] == {"nw": "1"}
    assert jar["exhentai.org"] == {"nw": "1", "ipb_member_id": "1", "ipb_pass_hash": "x"}


def test_check_access_needs_cookies_for_exhentai_only():
    Settings().check_access("https://e-hentai.org/g/1/ab/")
    Settings(ipb_member_id="1", ipb_pass_hash="x").check_access("https://exhentai.org/")
    with pytest.raises(SettingsError, match="EHENTAI_IPB_MEMBER_ID"):
        Settings().check_access("https://exhentai.org/")
