import importlib.util
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
