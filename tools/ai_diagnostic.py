"""Report Energy AI readiness without opening a connection or loading secrets."""

import json

from energy_optimizer.ai_integration import local_status


def main() -> int:
    print(json.dumps(local_status(), indent=2))
    # Readiness must not report success while the real connection is unavailable.
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
