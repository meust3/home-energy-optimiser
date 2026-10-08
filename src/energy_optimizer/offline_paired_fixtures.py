"""Only deliberately authored, byte-pinned fixtures; no arbitrary input path."""

import hashlib
import json
from pathlib import Path

from energy_optimizer.offline_paired_synthetic import (
    AdmissionError,
    SyntheticCase,
    case_from_dict,
    evaluate,
)

FIXTURE_SHA256 = {
    "native_A_two_hours": (
        "904e53053276d94181a4fc59b5bed3b3" "3eb12a50702c1f2edd62a9ecd0e6acae"
    ),
    "native_C_one_hour": (
        "1419f54aa2819ee2fe7fff12d17570e7" "6359d14c1d3e0c97bcdece948c95994d"
    ),
    "day_charge_A_extension": (
        "33e7a695777c399544cdd5a793cfe332" "c31881e6a8822468ac7b2e45f7734d3b"
    ),
    "day_preserve_C_extension": (
        "dd819711cc8a0f1bbedd4b503eb1db94" "31e38e54ea57c5997a62153b6bc70d85"
    ),
    "day_hold_identity": (
        "e6887cae1551418e83ce98ce6411b513" "352468f3a3d49da847c96484e519278b"
    ),
    "day_initial_policy_shortfall": (
        "4acb1b92393474a875a5d2f441eb0fd8" "12c1ad9900ce9af21c170243c7082f58"
    ),
    "day_solar_curtailment": (
        "e0e7056d1f42fe35ecc116e509afef72" "46c2e43831f32144f0139d30d787d4eb"
    ),
    "day_charge_import_headroom": (
        "cffe6d0804fef32e55a0111a4604846e" "e1473ee0adc4949ed188e08c8d8823fa"
    ),
    "day_unserved_load": (
        "08352d3d99576c661c23e954c9f795aa" "360a45a17a4ebc08f9cb29c2e6850971"
    ),
    "native_B_supplied_export_ledger": (
        "e38b39089c9bba21fa8ad8047799620b" "df9814f2b99a997e4c601bce17661f5d"
    ),
}
PUBLIC_FIXTURES = (
    "day_charge_A_extension",
    "day_preserve_C_extension",
    "day_hold_identity",
    "day_initial_policy_shortfall",
    "day_solar_curtailment",
    "day_charge_import_headroom",
    "day_unserved_load",
)


def load_fixture(name: str) -> dict:
    if name not in FIXTURE_SHA256:
        raise AdmissionError(["fixture_not_allowlisted"])
    path = (
        Path(__file__).resolve().parents[2]
        / "tests"
        / "fixtures"
        / "offline_paired_synthetic"
        / (name + ".json")
    )
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != FIXTURE_SHA256[name]:
        raise AdmissionError(["fixture_byte_hash_mismatch"])
    return json.loads(data)


def load_case(name: str) -> SyntheticCase:
    return case_from_dict(load_fixture(name))


def evaluate_fixture(name: str) -> dict:
    if name not in PUBLIC_FIXTURES:
        raise AdmissionError(["public_cli_accepts_only_authored_24h_fixtures"])
    result = evaluate(load_case(name))
    root = Path(__file__).resolve().parent
    result["fixture_file_sha256"] = FIXTURE_SHA256[name]
    result["implementation_source_sha256"] = {
        file: hashlib.sha256((root / file).read_bytes()).hexdigest()
        for file in ("offline_paired_synthetic.py", "offline_paired_fixtures.py")
    }
    return result
