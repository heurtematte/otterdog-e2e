"""Instance names and the env file writer (onboard.envfile): values round-trip through settings.parse_env_text, comments
and unrelated lines are kept, writes are atomic, 0600, never through a symlink."""

from __future__ import annotations

import os
import random
import re
import stat
from pathlib import Path

import pytest

from otterdog_e2e.onboard import envfile
from otterdog_e2e.onboard.envfile import (
    EnvFileError,
    InstanceNameError,
    check_instance_name,
    format_env_value,
    instance_app_dir,
    instance_env_path,
    known_instances,
    read_env_file,
    update_env_file,
)
from otterdog_e2e.safety import SafetyError
from otterdog_e2e.settings import parse_env_text

# every character class the quoting must survive: quotes, backslashes, $, # (inline comments), blanks, line breaks
ALPHABET = list("abcXYZ019_-./:@%+,=~^") + list("\"'\\$#` \t\n\r") + ["é", "€", "${", "\\n", "\\$", " #", '\\"']
EXISTING = """# otterdog-e2e instance test
# a comment that mentions E2E_ADMIN_TOKEN=not-a-value

export E2E_ORG=e2e-test-org   # inline comment
E2E_APP_PRIVATE_KEY="-----BEGIN PRIVATE KEY-----
abc
-----END PRIVATE KEY-----"
not an assignment line
E2E_ADMIN_TOKEN='old-token-1'
E2E_ADMIN_LOGIN=e2e-admin
E2E_ADMIN_TOKEN=old-token-2
"""


def _mode(path: Path) -> int:
    """Permission bits of a path."""
    return stat.S_IMODE(os.stat(path).st_mode)


def random_value(rng: random.Random) -> str:
    """A random value mixing every delicate character (sometimes empty, sometimes with outer blanks)."""
    value = "".join(rng.choice(ALPHABET) for _ in range(rng.randint(0, 24)))
    return rng.choice(["", " ", "\t", "\n"]) + value + rng.choice(["", " ", "\n"]) if rng.random() < 0.3 else value


# --- instance names -------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("name", ["free", "team", "enterprise", "free2", "a", "e2e-org-b", "x" * 39, "0abc"])
def test_valid_instance_names(name: str) -> None:
    """INSTANCE_NAME_RE: lower-case letters, digits and '-', 1 to 39 characters, no leading '-'."""
    assert check_instance_name(name) == name


@pytest.mark.parametrize(
    "name",
    [
        "",
        "-free",
        "Free",
        "free_2",
        "free.2",
        "a,b",
        "@all",
        "x" * 40,
        "free/x",
        "free\n",
        "free-untrusted",
        "org-webui",
        "lists",
    ],
)
def test_invalid_instance_names(name: str) -> None:
    """Anything else, lists and the reserved CI environment suffixes are refused."""
    with pytest.raises(InstanceNameError):
        check_instance_name(name)


def test_the_lists_directory_is_no_instance(tmp_path: Path) -> None:
    """~/.config/otterdog-e2e/lists/ holds the target lists (@<list>): ``lists`` is refused as an instance, so the
    App credentials of the manifest exchange (instance_app_dir) never land among the lists."""
    with pytest.raises(InstanceNameError, match=r"invalid instance name 'lists': the name is reserved"):
        instance_app_dir("lists", {"HOME": str(tmp_path)})
    with pytest.raises(InstanceNameError, match="reserved"):
        instance_env_path("lists", {"HOME": str(tmp_path)})
    assert check_instance_name("lists-2") == "lists-2"


def test_instance_paths_use_the_home_of_the_environ(tmp_path: Path) -> None:
    """~/.config/otterdog-e2e/<instance>.env and the App credentials dir, HOME taken from the given environ."""
    environ = {"HOME": str(tmp_path)}
    assert instance_env_path("free2", environ) == tmp_path / ".config" / "otterdog-e2e" / "free2.env"
    assert instance_app_dir("free2", environ) == tmp_path / ".config" / "otterdog-e2e" / "free2"
    with pytest.raises(InstanceNameError):
        instance_env_path("../x", environ)


def test_known_instances_lists_valid_env_files(tmp_path: Path) -> None:
    """Every <instance>.env with a valid name; other files and the App directories are ignored."""
    directory = tmp_path / ".config" / "otterdog-e2e"
    (directory / "free").mkdir(parents=True)
    for name in ("free.env", "org-b.env", "Bad_Name.env", "notes.txt", "x-webui.env"):
        (directory / name).write_text("")
    (directory / "free" / "app-1.env").write_text("")
    assert known_instances({"HOME": str(tmp_path)}) == {
        "free": directory / "free.env",
        "org-b": directory / "org-b.env",
    }
    assert known_instances({"HOME": str(tmp_path / "nowhere")}) == {}


# --- value quoting --------------------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("value", "rendered"),
    [
        ("e2e-test-org", "e2e-test-org"),
        ("1\n", '"1\\n"'),
        ("123456", "123456"),
        (
            "/home/u/.config/otterdog-e2e/free/app-1.private-key.pem",
            "/home/u/.config/otterdog-e2e/free/app-1.private-key.pem",
        ),
        ("https://example.org/hook?a=1", "https://example.org/hook?a=1"),
        ("", '""'),
        ("two words", '"two words"'),
        ('a"b', '"a\\"b"'),
        ("a\\b", '"a\\\\b"'),
        ("$HOME", '"\\$HOME"'),
        ("line1\nline2", '"line1\\nline2"'),
        ("x #y", '"x #y"'),
        ("'quoted'", "\"'quoted'\""),
    ],
)
def test_format_env_value(value: str, rendered: str) -> None:
    """Plain values stay unquoted, everything else is double-quoted with escapes; parse_env_text reads it back."""
    assert format_env_value(value) == rendered
    assert parse_env_text(f"K={rendered}\n") == {"K": value}


def test_format_env_value_round_trips_random_values() -> None:
    """Property: parse_env_text(KEY=format_env_value(v)) == v for random values of every delicate character."""
    rng = random.Random(20261005)
    for _ in range(3000):
        value = random_value(rng)
        assert parse_env_text(f"KEY={format_env_value(value)}\n") == {"KEY": value}, repr(value)


@pytest.mark.parametrize("char", ["\x00", "\x0b", "\x0c", "\x1c", "\x1d", "\x1e", "\x85", "\u2028", "\u2029"])
def test_unrepresentable_values_are_refused_without_the_value(char: str) -> None:
    """Line separators parse_env_text cannot read back (and NUL): EnvFileError naming the key, never the value."""
    with pytest.raises(EnvFileError) as error:
        format_env_value(f"secret-part{char}rest", key="E2E_X_TOKEN")
    assert "E2E_X_TOKEN" in str(error.value) and "secret-part" not in str(error.value)


# --- update_env_file ------------------------------------------------------------------------------------------------
def test_round_trip_property_through_the_file(tmp_path: Path) -> None:
    """Property: after any sequence of updates, parse_env_text of the file equals the expected mapping."""
    rng = random.Random(42)
    path = tmp_path / "cfg" / "x.env"
    path.parent.mkdir()
    path.write_text(EXISTING)
    expected = parse_env_text(EXISTING)
    keys = ["E2E_ORG", "E2E_ADMIN_TOKEN", "E2E_APP_PRIVATE_KEY", "E2E_NEW_A", "E2E_NEW_B", "E2E_ADMIN_LOGIN"]
    for _ in range(300):
        updates: dict[str, str | None] = {
            key: (None if rng.random() < 0.2 else random_value(rng)) for key in rng.sample(keys, rng.randint(1, 3))
        }
        update_env_file(path, updates)
        for key, value in updates.items():
            if value is None:
                expected.pop(key, None)
            else:
                expected[key] = value
        assert parse_env_text(path.read_text()) == expected
    assert "# a comment that mentions E2E_ADMIN_TOKEN=not-a-value\n" in path.read_text()
    assert "not an assignment line\n" in path.read_text()


def test_unrelated_lines_and_comments_are_kept_byte_for_byte(tmp_path: Path) -> None:
    """Replacing one key leaves every other line (comments, blank lines, export, multi-line PEM) untouched."""
    path = tmp_path / "x.env"
    path.write_text(EXISTING)
    assert update_env_file(path, {"E2E_ADMIN_LOGIN": "new-admin"}) == ["E2E_ADMIN_LOGIN"]
    assert path.read_text() == EXISTING.replace("E2E_ADMIN_LOGIN=e2e-admin", "E2E_ADMIN_LOGIN=new-admin")


def test_the_last_assignment_is_replaced_in_place_and_earlier_ones_dropped(tmp_path: Path) -> None:
    """Duplicates: the last one becomes the new value (same line), earlier ones (a former secret) disappear."""
    path = tmp_path / "x.env"
    path.write_text(EXISTING)
    update_env_file(path, {"E2E_ADMIN_TOKEN": "ghp_new"})
    text = path.read_text()
    assert "old-token-1" not in text and "old-token-2" not in text
    lines = text.splitlines()
    assert lines[-1] == "E2E_ADMIN_TOKEN=ghp_new" and lines[-2] == "E2E_ADMIN_LOGIN=e2e-admin"
    assert parse_env_text(text)["E2E_ADMIN_TOKEN"] == "ghp_new"


def test_export_prefix_is_kept(tmp_path: Path) -> None:
    """``export KEY=`` stays an export line."""
    path = tmp_path / "x.env"
    path.write_text(EXISTING)
    update_env_file(path, {"E2E_ORG": "Other-Org"})
    assert "export E2E_ORG=Other-Org\n" in path.read_text()


def test_a_multi_line_value_is_replaced_and_removed_entirely(tmp_path: Path) -> None:
    """A quoted value spanning several lines is one assignment: replaced or removed as a whole."""
    path = tmp_path / "x.env"
    path.write_text(EXISTING)
    update_env_file(path, {"E2E_APP_PRIVATE_KEY": "new\nkey"})
    text = path.read_text()
    assert "BEGIN PRIVATE KEY" not in text and 'E2E_APP_PRIVATE_KEY="new\\nkey"\n' in text
    assert update_env_file(path, {"E2E_APP_PRIVATE_KEY": None}) == ["E2E_APP_PRIVATE_KEY"]
    assert "E2E_APP_PRIVATE_KEY" not in path.read_text()
    assert parse_env_text(path.read_text()) == {
        "E2E_ORG": "e2e-test-org",
        "E2E_ADMIN_TOKEN": "old-token-2",
        "E2E_ADMIN_LOGIN": "e2e-admin",
    }


def test_none_removes_every_assignment_of_a_key(tmp_path: Path) -> None:
    """Removing a duplicated key removes all of its lines (an earlier one would otherwise become effective)."""
    path = tmp_path / "x.env"
    path.write_text(EXISTING)
    assert update_env_file(path, {"E2E_ADMIN_TOKEN": None, "E2E_MISSING": None}) == ["E2E_ADMIN_TOKEN"]
    assert "E2E_ADMIN_TOKEN=" not in path.read_text().replace("mentions E2E_ADMIN_TOKEN=", "")


def test_new_keys_are_appended_after_a_last_line_without_newline(tmp_path: Path) -> None:
    """New keys go to the end; a last line without newline gets one first."""
    path = tmp_path / "x.env"
    path.write_text("# head\nA=1")
    assert update_env_file(path, {"B": "two words", "C": "3"}) == ["B", "C"]
    assert path.read_text() == '# head\nA=1\nB="two words"\nC=3\n'


def test_a_new_file_gets_the_header_dir_0700_and_mode_0600(tmp_path: Path) -> None:
    """Created with the header comment lines, the missing directory 0700, the file 0600."""
    path = tmp_path / "home" / ".config" / "otterdog-e2e" / "x.env"
    assert update_env_file(path, {"E2E_ORG": "org"}, header="instance x\n# second line") == ["E2E_ORG"]
    assert path.read_text() == "# instance x\n# second line\nE2E_ORG=org\n"
    assert _mode(path) == 0o600 and _mode(path.parent) == 0o700
    update_env_file(path, {"E2E_ORG_ID": "1"}, header="never added again")
    assert "never added again" not in path.read_text()


def test_an_existing_shared_file_is_tightened_to_0600(tmp_path: Path) -> None:
    """A rewrite always produces a 0600 file (the temp file is created 0600 and renamed)."""
    path = tmp_path / "x.env"
    path.write_text("A=1\n")
    path.chmod(0o644)
    update_env_file(path, {"A": "2"})
    assert _mode(path) == 0o600


def test_unchanged_values_write_nothing(tmp_path: Path) -> None:
    """No effective change: nothing returned, the file is not rewritten (same inode, same mode)."""
    path = tmp_path / "x.env"
    path.write_text(EXISTING)
    path.chmod(0o640)
    before = os.stat(path).st_ino
    assert update_env_file(path, {"E2E_ORG": "e2e-test-org", "E2E_ADMIN_TOKEN": "old-token-2", "E2E_NONE": None}) == []
    assert os.stat(path).st_ino == before and path.read_text() == EXISTING and _mode(path) == 0o640


def test_only_key_names_are_returned(tmp_path: Path) -> None:
    """The result lists names, never values."""
    changed = update_env_file(tmp_path / "x.env", {"E2E_ADMIN_TOKEN": "ghp_secretvalue", "E2E_ORG": "o"})
    assert changed == ["E2E_ADMIN_TOKEN", "E2E_ORG"]


def test_symlinks_are_refused(tmp_path: Path) -> None:
    """A symlinked env file or directory is never written through; the link target stays untouched."""
    real = tmp_path / "real.env"
    real.write_text("A=1\n")
    link = tmp_path / "link.env"
    link.symlink_to(real)
    with pytest.raises(SafetyError, match="symlink"):
        update_env_file(link, {"A": "2"})
    real_dir = tmp_path / "real-dir"
    real_dir.mkdir()
    (tmp_path / "dir-link").symlink_to(real_dir)
    with pytest.raises(SafetyError, match="symlinked directory"):
        update_env_file(tmp_path / "dir-link" / "x.env", {"A": "2"})
    assert real.read_text() == "A=1\n" and not list(real_dir.iterdir())


def test_a_non_regular_file_is_refused(tmp_path: Path) -> None:
    """A directory (or any special file) at the path is refused."""
    (tmp_path / "x.env").mkdir()
    with pytest.raises(SafetyError, match="not a regular file"):
        update_env_file(tmp_path / "x.env", {"A": "1"})


def test_bad_keys_and_unterminated_quotes_are_refused(tmp_path: Path) -> None:
    """Invalid names and a file whose unterminated quote would swallow the appended keys."""
    path = tmp_path / "x.env"
    with pytest.raises(EnvFileError, match="invalid env variable name"):
        update_env_file(path, {"BAD-NAME": "1"})
    path.write_text('A=1\nB="never closed\nC=3\n')
    with pytest.raises(EnvFileError, match=re.escape("x.env:2: B has an unterminated quoted value")):
        update_env_file(path, {"D": "4"})
    assert path.read_text() == 'A=1\nB="never closed\nC=3\n'


def test_a_failed_write_leaves_the_file_and_no_temp_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Atomic: when the rename fails, the original file is intact and the temp file removed."""
    path = tmp_path / "x.env"
    path.write_text("A=1\n")

    def broken_replace(source: str | os.PathLike[str], destination: str | os.PathLike[str]) -> None:
        """os.replace failing like a full disk."""
        raise OSError("disk full")

    monkeypatch.setattr(envfile.os, "replace", broken_replace)
    with pytest.raises(OSError, match="disk full"):
        update_env_file(path, {"A": "2"})
    assert path.read_text() == "A=1\n" and [entry.name for entry in tmp_path.iterdir()] == ["x.env"]


def test_read_env_file(tmp_path: Path) -> None:
    """The values parse_env_text sees; a missing file is empty."""
    path = tmp_path / "x.env"
    assert read_env_file(path) == {}
    path.write_text(EXISTING)
    assert read_env_file(path) == parse_env_text(EXISTING)
