"""Secret redaction for every text the harness logs, prints or writes to artifacts (SPEC 5.8, SEC-09).

``REDACTOR`` is the process-wide instance: credentials are registered when loaded (settings.load_env_files) or minted
(AppAuth JWTs and installation tokens, the webapp SECRET_KEY and webhook secret). Besides literal values and their
transformed forms (base64, URL/JSON escaping, compose ``$$`` escaping), well-known token shapes are always redacted.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re
import sys
import threading
import urllib.parse
import weakref
from collections.abc import Callable, Iterable
from pathlib import Path

MASK = "***"
MIN_SECRET_LENGTH = 6
PEM_LINE_MIN_LENGTH = 20
SECRET_KEY_RE = re.compile(r"(_TOKEN|_SECRET|_PASSWORD|_TOTP_SEED|_PRIVATE_KEY)$")


_mask_sink: Callable[[str], None] | None = None


def set_mask_sink(sink: Callable[[str], None] | None) -> None:
    """Route ``::add-mask::`` lines to ``sink`` (e.g. a writer that bypasses pytest capture); None means sys.stdout."""
    global _mask_sink
    _mask_sink = sink


def mask_sink() -> Callable[[str], None] | None:
    """The sink set by set_mask_sink (None: sys.stdout)."""
    return _mask_sink


def fd_mask_sink(fd: int) -> Callable[[str], None]:
    """A thread-safe sink writing whole lines to the file descriptor ``fd`` (the runner's original stdout, which
    pytest's fd capture does not redirect)."""
    lock = threading.Lock()

    def write(line: str) -> None:
        """Write ``line`` completely (workflow commands must not interleave)."""
        data = line.encode("utf-8", "replace")
        with lock:
            while data:
                data = data[os.write(fd, data) :]

    return write


def _write_mask_line(line: str) -> None:
    """Write one workflow-command line to the configured sink or to stdout."""
    if _mask_sink is not None:
        _mask_sink(line)
        return
    sys.stdout.write(line)
    sys.stdout.flush()


def _escape_workflow_command(value: str) -> str:
    """Escape a value for a GitHub Actions workflow command (``%``, CR and LF)."""
    return value.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


class Redactor:
    """Replaces registered secrets (and their variants) and token-shaped strings with ``***``."""

    PATTERNS = (
        r"gh[pousr]_[A-Za-z0-9_]{36,255}",
        r"github_pat_[A-Za-z0-9_]{22,255}",
        r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}",
        r"(?s)-----BEGIN [A-Z ]*PRIVATE KEY-----.+?-----END [A-Z ]*PRIVATE KEY-----",
    )

    def __init__(self, secrets: Iterable[str | None] = ()) -> None:
        """Create a redactor and register ``secrets`` (with variants)."""
        self._lock = threading.RLock()
        self._literals: set[str] = set()
        self._masked: set[str] = set()
        self._text_re: re.Pattern[str] | None = None
        self._bytes_re: re.Pattern[bytes] | None = None
        self._text_patterns = [re.compile(p) for p in self.PATTERNS]
        self._bytes_patterns = [re.compile(p.encode()) for p in self.PATTERNS]
        self.add(*secrets)

    @property
    def literals(self) -> frozenset[str]:
        """Every registered literal (secrets and their variants)."""
        with self._lock:
            return frozenset(self._literals)

    def add(self, *values: str | None, variants: bool = True) -> None:
        """Register secrets; None and values shorter than 6 chars are ignored, variants cover transformed forms."""
        for value in values:
            if value is None or len(value) < MIN_SECRET_LENGTH:
                continue
            forms = self._variants(value) if variants else {value}
            with self._lock:
                new = forms - self._literals
                if not new:
                    continue
                self._literals |= new
                self._text_re = None
                self._bytes_re = None
            self._mask_in_actions(new)

    @staticmethod
    def _variants(value: str) -> set[str]:
        """The value plus base64, x-access-token base64, URL-quoted, JSON-escaped, ``$$``-escaped and PEM-line forms.

        Forms are computed for the value as given and for its whitespace-stripped form (tokens read from files often
        carry a trailing newline that never appears in output).
        """
        forms: set[str] = set()
        for current in {value, value.strip()}:
            forms.add(current)
            for raw in (current, "x-access-token:" + current):
                encoded = base64.b64encode(raw.encode()).decode()
                forms.update({encoded, encoded.rstrip("=")})
            forms.add(urllib.parse.quote(current, safe=""))
            forms.add(json.dumps(current)[1:-1])
            forms.add(current.replace("$", "$$"))
        if "-----BEGIN" in value:
            forms.update(line.strip() for line in value.splitlines() if len(line.strip()) > PEM_LINE_MIN_LENGTH)
        return {form for form in forms if len(form) >= MIN_SECRET_LENGTH}

    def _mask_in_actions(self, literals: Iterable[str]) -> None:
        """On GitHub Actions, emit ``::add-mask::`` once per single-line literal so runner logs are masked too."""
        if os.environ.get("GITHUB_ACTIONS") != "true":
            return
        for literal in sorted(literals):
            with self._lock:
                if literal in self._masked or "\n" in literal or "\r" in literal:
                    continue
                self._masked.add(literal)
            _write_mask_line(f"::add-mask::{_escape_workflow_command(literal)}\n")

    def _compiled(self) -> tuple[re.Pattern[str] | None, re.Pattern[bytes] | None]:
        """Alternation of all literals, longest first (compiled lazily, invalidated by add)."""
        with self._lock:
            if self._text_re is None and self._literals:
                ordered = sorted(self._literals, key=lambda s: (-len(s), s))
                self._text_re = re.compile("|".join(re.escape(s) for s in ordered))
                self._bytes_re = re.compile(b"|".join(re.escape(s.encode()) for s in ordered))
            return self._text_re, self._bytes_re

    def __call__(self, text: str) -> str:
        """Return ``text`` with literal secrets (longest first) and PATTERNS replaced by ``***``."""
        literal_re, _ = self._compiled()
        if literal_re is not None:
            text = literal_re.sub(MASK, text)
        for pattern in self._text_patterns:
            text = pattern.sub(MASK, text)
        return text

    def redact_bytes(self, data: bytes) -> bytes:
        """Bytes version of __call__ (literals are matched in their UTF-8 encoding)."""
        _, literal_re = self._compiled()
        if literal_re is not None:
            data = literal_re.sub(MASK.encode(), data)
        for pattern in self._bytes_patterns:
            data = pattern.sub(MASK.encode(), data)
        return data

    def contains_secret(self, data: bytes) -> bool:
        """True when ``data`` contains a registered literal or a token-shaped string."""
        _, literal_re = self._compiled()
        if literal_re is not None and literal_re.search(data):
            return True
        return any(pattern.search(data) for pattern in self._bytes_patterns)

    def redact_file(self, path: Path) -> None:
        """Redact a file in place (rewritten only when something was replaced)."""
        data = path.read_bytes()
        redacted = self.redact_bytes(data)
        if redacted != data:
            path.write_bytes(redacted)


REDACTOR = Redactor()


class RedactingFilter(logging.Filter):
    """Logging filter that redacts the formatted message, exception and stack text of each record."""

    def __init__(self, redactor: Redactor = REDACTOR) -> None:
        """Create a filter bound to ``redactor``."""
        super().__init__()
        self.redactor = redactor

    def filter(self, record: logging.LogRecord) -> bool:
        """Redact ``record`` in place; never drops it."""
        redact_record(record, self.redactor)
        return True


def redact_record(record: logging.LogRecord, redactor: Redactor = REDACTOR) -> None:
    """Replace a record's message (args merged), exception text and stack info by their redacted forms."""
    try:
        message = record.getMessage()
    except (TypeError, ValueError, KeyError):  # a broken format string must not break logging
        message = str(record.msg)
    record.msg = redactor(message)
    record.args = None
    if record.exc_info and not record.exc_text:
        record.exc_text = logging.Formatter().formatException(record.exc_info)
    if record.exc_text:
        record.exc_text = redactor(record.exc_text)
    if record.stack_info:
        record.stack_info = redactor(record.stack_info)


_installed: weakref.WeakSet[Redactor] = weakref.WeakSet()
_install_lock = threading.Lock()


def install_logging_filter(redactor: Redactor = REDACTOR) -> None:
    """Redact every log record at creation (record factory), so all handlers, pytest's included, see redacted text."""
    with _install_lock:
        if redactor in _installed:
            return
        _installed.add(redactor)
        previous = logging.getLogRecordFactory()

        def factory(*args: object, **kwargs: object) -> logging.LogRecord:
            """Build the record with the previous factory, then redact it."""
            record = previous(*args, **kwargs)
            redact_record(record, redactor)
            return record

        logging.setLogRecordFactory(factory)
