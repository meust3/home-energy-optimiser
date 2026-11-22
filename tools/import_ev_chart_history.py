"""Import reviewed EV evidence for dashboard display. No device or forecast writes."""

import argparse
import json
from pathlib import Path

from energy_optimizer.db.models import ArbitrageCapture, ArbitrageCommitWitness
from energy_optimizer.ev_chart import import_history
from energy_optimizer.persistence import open_repository


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("overlay", type=Path)
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument(
        "--offline-sqlite", type=Path, help="Private local chart archive"
    )
    target.add_argument(
        "--configured-database",
        action="store_true",
        help="Use the existing configured schema",
    )
    args = parser.parse_args()
    url = (
        f"sqlite:///{args.offline_sqlite.resolve().as_posix()}"
        if args.offline_sqlite
        else None
    )
    repository = open_repository(url)
    try:
        if args.offline_sqlite:
            for table in (ArbitrageCapture.__table__, ArbitrageCommitWitness.__table__):
                table.create(repository.engine, checkfirst=True)
        rows = json.loads(args.overlay.read_text(encoding="utf-8-sig"))
        count = import_history(repository, rows)
        print(f"Verified {count} distinct EV evidence slots.")
    finally:
        repository.close()


if __name__ == "__main__":
    main()
