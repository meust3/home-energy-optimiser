import importlib.util
import threading
from pathlib import Path


def load_tool():
    path = Path(__file__).parents[1] / "tools" / "run_collector.py"
    spec = importlib.util.spec_from_file_location("run_collector", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_boundary_calculation_avoids_drift():
    module = load_tool()
    assert module.seconds_to_next_boundary(601, 300) == 299


def test_keyboard_interrupt_propagates_for_clean_main_handling():
    module = load_tool()

    def interrupt(_delay):
        raise KeyboardInterrupt

    try:
        module.run(lambda: None, interval=300, sleep=interrupt, clock=lambda: 601)
    except KeyboardInterrupt:
        pass
    else:
        raise AssertionError("KeyboardInterrupt did not propagate")


def test_database_connection_retry_is_bounded():
    module = load_tool()
    attempts = []
    delays = []

    def save():
        attempts.append(1)
        if len(attempts) < 3:
            raise module.DatabaseConnectionError("temporary")
        return "saved"

    assert module.save_with_retry(save, sleep=delays.append) == "saved"
    assert len(attempts) == 3
    assert delays == [1, 2]


def test_stop_event_prevents_future_collection_attempts():
    module = load_tool()
    stop = threading.Event()
    stop.set()
    calls = []
    module.run(lambda: calls.append(1), interval=300, stop_event=stop)
    assert calls == []
