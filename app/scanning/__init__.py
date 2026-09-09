from __future__ import annotations

import socket
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum


class ScanOutcome(str, Enum):
    CLEAN = "CLEAN"
    INFECTED = "INFECTED"


@dataclass
class ScanResult:
    outcome: ScanOutcome
    # Set only when outcome == INFECTED - the signature ClamAV matched
    # (e.g. "Win.Test.EICAR_HDB-1"), stored verbatim on
    # DocumentVersion.malware_signature for an auto-quarantined version.
    signature_name: str | None = None


class ScannerUnavailable(Exception):
    """
    Raised, not returned - the scanner couldn't be reached, the
    connection/scan timed out, or it returned an inconclusive result
    (clamd's own ERROR response - a stream it couldn't finish scanning,
    e.g. one exceeding its own configured StreamMaxLength). Treated
    identically to "can't reach it" for fail-closed purposes: a file
    that couldn't be conclusively scanned is never treated as CLEAN.
    See CLAUDE.md "Malware scanning".
    """


class MalwareScanner(ABC):
    """
    Storage interface for malware scanning (AC-FR-04-01), mirroring
    app/storage/DocumentStorage's own shape - a new top-level package,
    parallel to it, a technical layer not a domain module. One method:
    no separate ping()/is_available() exists because this synchronous
    design only ever calls scan() - a connection failure surfaces
    naturally as ScannerUnavailable from that one call, so a health-
    check method would be surface area with no real call site.
    """

    @abstractmethod
    def scan(self, content: bytes) -> ScanResult:
        ...


class NoOpScanner(MalwareScanner):
    """
    Always CLEAN - for local dev and tests, mirroring
    LocalFilesystemStorage's own role. The default backend
    (Settings.malware_scanner_backend == "noop") - see CLAUDE.md
    "Malware scanning" for why that default is deliberately named and
    flagged, not just convenient.
    """

    def scan(self, content: bytes) -> ScanResult:
        return ScanResult(outcome=ScanOutcome.CLEAN)


class ClamAVScanner(MalwareScanner):
    """
    Talks to a clamd daemon (ClamAV's scanning daemon) over TCP via the
    `clamd` package's INSTREAM protocol client - a real, if narrow,
    dependency this ticket adds (see CLAUDE.md "Malware scanning" for
    why it was chosen over hand-rolling the wire protocol).
    """

    def __init__(self, host: str, port: int, timeout: float):
        self.host = host
        self.port = port
        self.timeout = timeout

    def scan(self, content: bytes) -> ScanResult:
        import io

        import clamd as clamd_module

        client = clamd_module.ClamdNetworkSocket(
            host=self.host,
            port=self.port,
            timeout=self.timeout,
        )

        try:
            response = client.instream(io.BytesIO(content))
        except (OSError, socket.timeout) as exc:
            raise ScannerUnavailable(f"Could not reach ClamAV: {exc}") from exc
        except clamd_module.ClamdError as exc:
            # Covers clamd's own ConnectionError and BufferTooLongError
            # (a stream longer than clamd's own configured
            # StreamMaxLength) - protocol-level problems, not
            # necessarily surfaced as an OSError. Any of these means
            # "no conclusive answer was obtained", the same fail-closed
            # bucket as an unreachable daemon, not a plain scan-and-
            # move-on failure. A genuinely unexpected exception (a bug
            # in this code, not a clamd/network problem) is
            # deliberately NOT caught here - it should propagate, not
            # be silently folded into "scanner unavailable".
            raise ScannerUnavailable(f"ClamAV scan did not complete: {exc}") from exc

        # response shape: {"stream": ("OK", None)} or
        # {"stream": ("FOUND", "<signature>")} or
        # {"stream": ("ERROR", "<detail>")}
        status, detail = response.get("stream", (None, None))

        if status == "OK":
            return ScanResult(outcome=ScanOutcome.CLEAN)
        if status == "FOUND":
            return ScanResult(outcome=ScanOutcome.INFECTED, signature_name=detail)

        raise ScannerUnavailable(f"ClamAV returned an inconclusive result: {detail}")
