from energy_optimizer.power_signs import analyze_power_signs


def test_sign_analysis_ranks_hypotheses_and_reports_modes():
    rows = []
    for index in range(40):
        grid = 1500 + index * 10
        battery = 500 + index * 5
        pv = 1000 + index * 3
        house = pv + grid + battery
        rows.append(
            {
                "pv_power_w": pv,
                "house_consumption_w": house,
                "grid_power_w": grid,
                "battery_power_w": battery,
                "battery_mode": "Discharging",
            }
        )
    rows.append({"pv_power_w": None})
    result = analyze_power_signs(rows)
    leading = result["leading_hypothesis"]
    assert result["sample_count"] == 40
    assert result["excluded_incomplete_samples"] == 1
    assert leading["grid_multiplier"] == 1
    assert leading["battery_multiplier"] == 1
    assert leading["root_mean_square_residual_w"] == 0
    assert result["confidence"] in {"medium", "high"}
    assert result["battery_mode_evidence"][0]["sample_count"] == 40
    assert "no sign convention" in result["disclaimer"].lower()


def test_sign_analysis_reports_insufficient_data():
    result = analyze_power_signs([])
    assert result["leading_hypothesis"] is None
    assert result["confidence"] == "insufficient_data"
