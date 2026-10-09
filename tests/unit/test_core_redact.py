"""WP-A: secret redaction, its variants and GitHub Actions masking (SPEC 5.8, SEC-09)."""

from __future__ import annotations

import base64
import contextlib
import json
import logging
import sys
import threading
import urllib.parse
from pathlib import Path

import pytest

from otterdog_e2e import redact
from otterdog_e2e.redact import MASK, SECRET_KEY_RE, RedactingFilter, Redactor

SECRET = "wpa$secret/value+1"
PEM = (
    "-----BEGIN RSA PRIVATE KEY-----\n"
    "MIIEowIBAAKCAQEAwpaPemLineNumberOne0123456789\n"
    "abcdefghijklmnopqrstuvwxyzPemLineTwo\n"
    "short\n"
    "-----END RSA PRIVATE KEY-----\n"
)


@pytest.fixture
def mask_lines(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Collect ::add-mask:: lines as if running on GitHub Actions."""
    lines: list[str] = []
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    previous = redact.mask_sink()
    redact.set_mask_sink(lines.append)
    yield lines
    redact.set_mask_sink(previous)


@pytest.mark.parametrize(
    "form",
    [
        SECRET,
        base64.b64encode(SECRET.encode()).decode(),
        base64.b64encode(SECRET.encode()).decode().rstrip("="),
        base64.b64encode(f"x-access-token:{SECRET}".encode()).decode(),
        urllib.parse.quote(SECRET, safe=""),
        json.dumps(SECRET)[1:-1],
        SECRET.replace("$", "$$"),
    ],
)
def test_every_variant_is_redacted(form: str) -> None:
    """Literal, base64 (padded or not), git basic-auth base64, URL-quoted, JSON-escaped and compose $$ forms."""
    assert Redactor([SECRET])(f"<{form}>") == f"<{MASK}>"


def test_values_are_also_registered_stripped() -> None:
    """A token read with a trailing newline is redacted as printed (without it), base64 forms included."""
    redactor = Redactor(["wpa-file-token-77\n"])
    assert redactor("auth wpa-file-token-77 ok") == f"auth {MASK} ok"
    encoded = base64.b64encode(b"x-access-token:wpa-file-token-77").decode()
    assert redactor(f"Basic {encoded}") == f"Basic {MASK}"


def test_regex_metacharacters_and_unicode_are_literal() -> None:
    """Secrets are escaped in the alternation; non-ASCII secrets work in text and bytes."""
    redactor = Redactor(["a+b(c)[d]*e?", "pässwörd-ü1"])
    assert redactor("x a+b(c)[d]*e? y abbbbcde") == f"x {MASK} y abbbbcde"
    assert redactor.redact_bytes("pässwörd-ü1!".encode()) == f"{MASK}!".encode()


def test_ignored_values_and_variants_flag() -> None:
    """None and values shorter than 6 characters are never registered; variants=False registers the literal only."""
    redactor = Redactor([None, "", "12345"])
    assert redactor.literals == frozenset()
    redactor.add("wpa-literal-only", variants=False)
    assert redactor.literals == frozenset({"wpa-literal-only"})


def test_pem_keys_are_redacted_whole_line_by_line_and_escaped() -> None:
    """Whole PEMs, each long line (wrapped logs), the JSON-escaped form; short lines are not literals."""
    redactor = Redactor([PEM])
    assert redactor(f"key: {PEM}") == f"key: {MASK}"
    assert redactor("MIIEowIBAAKCAQEAwpaPemLineNumberOne0123456789") == MASK
    assert redactor(json.dumps({"key": PEM})) == json.dumps({"key": MASK})
    assert "short" not in redactor.literals


@pytest.mark.parametrize(
    ("text", "redacted"),
    [
        ("ghp_" + "a" * 35, False),
        ("ghp_" + "a" * 36, True),
        ("gho_" + "B" * 40, True),
        ("ghu_" + "1" * 36, True),
        ("ghs_" + "x_" * 20, True),
        ("ghr_" + "z" * 50, True),
        ("ghx_" + "a" * 40, False),
        ("github_pat_" + "A" * 21, False),
        ("github_pat_" + "A1_" * 30, True),
        ("eyJhbGciOiJSUzI1NiJ9.eyJpc3MiOiIxMjM0NSJ9.c2lnbmF0dXJlLXZhbHVl", True),
        ("eyJshort.eyJshort.sig", False),
        ("-----BEGIN PRIVATE KEY-----\nabc\n-----END PRIVATE KEY-----", True),
        ("-----BEGIN EC PRIVATE KEY-----\nabc\n-----END EC PRIVATE KEY-----", True),
        ("-----BEGIN PUBLIC KEY-----\nabc\n-----END PUBLIC KEY-----", False),
    ],
)
def test_token_shapes(text: str, redacted: bool) -> None:
    """PATTERNS redact GitHub tokens, JWTs and private keys even when never registered."""
    result = Redactor()(f"[{text}]")
    assert (result == f"[{MASK}]") is redacted
    assert Redactor().contains_secret(text.encode()) is redacted


def test_contains_secret_and_redact_bytes() -> None:
    """Byte scanning uses the same literals and patterns."""
    redactor = Redactor([SECRET])
    data = f"a {SECRET} b".encode()
    assert redactor.contains_secret(data)
    assert redactor.redact_bytes(data) == f"a {MASK} b".encode()
    assert not redactor.contains_secret(b"harmless")
    assert not Redactor().contains_secret(b"harmless")


def test_redact_file_rewrites_only_when_needed(tmp_path: Path) -> None:
    """Clean files are left untouched (same mtime); leaking files are rewritten."""
    redactor = Redactor([SECRET])
    clean = tmp_path / "clean.txt"
    clean.write_text("nothing to see", encoding="utf-8")
    before = clean.stat().st_mtime_ns
    redactor.redact_file(clean)
    assert clean.stat().st_mtime_ns == before
    leaking = tmp_path / "leak.log"
    leaking.write_text(f"token={SECRET}\n", encoding="utf-8")
    redactor.redact_file(leaking)
    assert leaking.read_text(encoding="utf-8") == f"token={MASK}\n"


def test_add_mask_once_per_value_including_variants(mask_lines: list[str]) -> None:
    """On Actions every new single-line literal (variants included) is masked exactly once."""
    redactor = Redactor()
    redactor.add("wpa-mask-me-001")
    redactor.add("wpa-mask-me-001")
    masked = [line.removeprefix("::add-mask::").rstrip("\n") for line in mask_lines]
    assert len(masked) == len(set(masked))
    assert "wpa-mask-me-001" in masked
    assert base64.b64encode(b"wpa-mask-me-001").decode() in masked
    assert all(line.startswith("::add-mask::") and line.endswith("\n") for line in mask_lines)


def test_add_mask_escapes_and_skips_multiline_values(mask_lines: list[str]) -> None:
    """'%' is escaped; multi-line PEMs are masked through their individual lines."""
    redactor = Redactor()
    redactor.add("50%-off-secret", variants=False)
    redactor.add(PEM)
    assert "::add-mask::50%25-off-secret\n" in mask_lines
    assert not any("BEGIN RSA PRIVATE KEY-----\n" in line[:-1] for line in mask_lines)
    assert "::add-mask::MIIEowIBAAKCAQEAwpaPemLineNumberOne0123456789\n" in mask_lines


def test_no_add_mask_outside_actions(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """Nothing is printed unless GITHUB_ACTIONS == "true"."""
    monkeypatch.setenv("GITHUB_ACTIONS", "false")
    Redactor(["wpa-quiet-secret-1"])
    assert capsys.readouterr().out == ""


def test_secret_key_re_variants() -> None:
    """Only credential suffixes are secret keys (not *_FILE, *_ID, *_LOGIN, *_ENV)."""
    assert SECRET_KEY_RE.search("E2E_CONFIG_READER_TOKEN")
    assert SECRET_KEY_RE.search("E2E_OTTERDOG_TOTP_SEED")
    for key in ("E2E_APP_PRIVATE_KEY_FILE", "E2E_APP_ID", "E2E_OUTSIDER_LOGIN", "E2E_TOKEN_ENV", "TOKEN"):
        assert not SECRET_KEY_RE.search(key), key


def test_redacting_filter_handles_exceptions_and_bad_formats() -> None:
    """Exception text is redacted; a broken format string never breaks logging."""
    redactor = Redactor(["wpa-log-secret-01"])
    try:
        raise RuntimeError("failed with wpa-log-secret-01")
    except RuntimeError:
        record = logging.LogRecord("x", logging.ERROR, __file__, 1, "boom %s", ("wpa-log-secret-01",), sys.exc_info())
    assert RedactingFilter(redactor).filter(record)
    assert record.getMessage() == f"boom {MASK}"
    assert record.exc_text is not None and "wpa-log-secret-01" not in record.exc_text
    broken = logging.LogRecord("x", logging.INFO, __file__, 1, "%d wpa-log-secret-01", ("nan",), None)
    RedactingFilter(redactor).filter(broken)
    assert broken.getMessage() == f"%d {MASK}"


def test_concurrent_adds_and_redactions() -> None:
    """add() and __call__ are safe from several threads (relay thread + main thread)."""
    redactor = Redactor()
    errors: list[BaseException] = []

    def worker(index: int) -> None:
        """Register and redact concurrently."""
        try:
            for step in range(15):
                secret = f"wpa-thread-{index}-secret-{step:03d}"
                redactor.add(secret)
                assert redactor(f"x {secret} y") == f"x {MASK} y"
        except Exception as exc:  # noqa: BLE001 - re-reported by the main thread
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == []


def test_fd_mask_sink_writes_whole_lines_to_a_descriptor() -> None:
    """ISO-03: fd_mask_sink writes each line completely to the descriptor (the runner's real stdout)."""
    import os

    read_fd, write_fd = os.pipe()
    try:
        sink = redact.fd_mask_sink(write_fd)
        sink("::add-mask::abc\n")
        sink("::add-mask::d%0Ae\n")
        os.close(write_fd)
        with os.fdopen(read_fd, "rb") as handle:
            assert handle.read() == b"::add-mask::abc\n::add-mask::d%0Ae\n"
    finally:
        for fd in (read_fd, write_fd):
            with contextlib.suppress(OSError):
                os.close(fd)
