"""Defence-in-depth guard for these exclusively local research entry points."""

import sys


def guard(event, args):
    if event.startswith(
        (
            "socket.",
            "sqlite3.connect",
            "subprocess.",
            "os.system",
            "os.exec",
            "os.spawn",
        )
    ):
        raise RuntimeError("offline_guard:" + event)
    if event == "open" and isinstance(args[0], (str, bytes)):
        name = str(args[0]).replace("\\", "/").lower()
        if name.endswith((".env", ".db", ".sqlite", ".sqlite3")) or "/.env." in name:
            raise RuntimeError("offline_guard:secret_or_database_read")
    if event == "import" and str(args[0]).split(".")[0] in {
        "requests",
        "httpx",
        "psycopg",
        "psycopg2",
        "openai",
        "dotenv",
        "sqlalchemy",
    }:
        raise RuntimeError("offline_guard:runtime_import")


def install():
    sys.addaudithook(guard)
