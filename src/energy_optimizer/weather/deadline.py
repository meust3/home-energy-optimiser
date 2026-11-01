"""Enforce a streaming deadline at every socket read, including slow headers."""

from __future__ import annotations

import io
import time
from collections.abc import Callable
from typing import Any

from requests.adapters import HTTPAdapter
from urllib3.connection import HTTPSConnection
from urllib3.connectionpool import HTTPSConnectionPool


class DeadlineReader(io.RawIOBase):
    def __init__(
        self,
        transport: Any,
        deadline: float,
        clock: Callable[[], float] = time.monotonic,
        source: io.RawIOBase | None = None,
    ) -> None:
        self.transport, self.deadline, self.clock = transport, deadline, clock
        self.source = source

    def readable(self) -> bool:
        return True

    def readinto(self, buffer: Any) -> int:
        remaining = self.deadline - self.clock()
        if remaining <= 0:
            raise TimeoutError("WEATHER_RESPONSE_DEADLINE")
        self.transport.settimeout(min(10, remaining))
        return (
            self.source.readinto(buffer)
            if self.source
            else self.transport.recv_into(buffer)
        )

    def close(self) -> None:
        if self.source is not None:
            self.source.close()
        super().close()


class DeadlineSocket:
    def __init__(self, transport: Any, deadline: float) -> None:
        self.transport, self.deadline = transport, deadline

    def __getattr__(self, name: str) -> Any:
        return getattr(self.transport, name)

    def makefile(
        self, mode: str = "rb", *args: Any, **kwargs: Any
    ) -> io.BufferedReader:
        if mode != "rb":
            raise ValueError("WEATHER_READ_MODE")
        # Retain the socket's normal makefile reference count. HTTP/1.0 closes
        # the connection after headers, while the response still owns its file.
        source = self.transport.makefile(mode, buffering=0)
        return io.BufferedReader(
            DeadlineReader(self.transport, self.deadline, source=source)
        )


class DeadlineConnection(HTTPSConnection):
    deadline: float

    def connect(self) -> None:
        super().connect()
        self.sock = DeadlineSocket(self.sock, self.deadline)


class DeadlinePool(HTTPSConnectionPool):
    ConnectionCls = DeadlineConnection

    def __init__(self, *args: Any, deadline: float, **kwargs: Any) -> None:
        self.deadline = deadline
        super().__init__(*args, **kwargs)

    def _new_conn(self) -> DeadlineConnection:
        connection = super()._new_conn()
        connection.deadline = self.deadline
        return connection


def deadline_adapter(deadline: float) -> HTTPAdapter:
    adapter = HTTPAdapter(max_retries=0)
    # Per-session pool factory; do not mutate urllib3's shared class mapping.
    adapter.poolmanager.pool_classes_by_scheme = {
        **adapter.poolmanager.pool_classes_by_scheme,
        "https": lambda *args, **kwargs: DeadlinePool(
            *args, deadline=deadline, **kwargs
        ),
    }
    return adapter
