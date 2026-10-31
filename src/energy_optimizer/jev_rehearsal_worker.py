"""Private offline child: deterministic synthetic replies over pipes, no network."""

import json
import sys
from uuid import UUID, uuid5


def main() -> None:
    # The ephemeral nonce is received over a private pipe, never argv or a file.
    nonce = json.loads(sys.stdin.readline())["nonce"]
    for line in sys.stdin:
        request = json.loads(line)
        if request.pop("nonce", None) != nonce:
            return
        root = UUID(request["experiment_id"])
        response = {
            **request,
            "status": "completed",
            "execution": "offline_simulation",
            "event_id": str(uuid5(root, "event:" + request["case_id"])),
            "request_id": str(uuid5(root, "request:" + request["case_id"])),
            "raw_typed_answer": {
                "type": "choice",
                "choice": "needs_review",
                "probabilities": {
                    "supported": 0.0,
                    "needs_review": 1.0,
                    "insufficient_evidence": 0.0,
                },
            },
            "reported_usage": None,
        }
        print(json.dumps(response, allow_nan=False), flush=True)


if __name__ == "__main__":
    main()
