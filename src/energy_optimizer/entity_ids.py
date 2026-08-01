"""Central Home Assistant entity identifiers used by the collector."""

AMBER_IMPORT_PRICE = "sensor.amber_home_assistant_general_price"
AMBER_IMPORT_FORECAST = "sensor.amber_home_assistant_general_forecast"
AMBER_EXPORT_PRICE = "sensor.amber_home_assistant_feed_in_price"
AMBER_EXPORT_FORECAST = "sensor.amber_home_assistant_feed_in_forecast"
AMBER_PRICE_SPIKE = "binary_sensor.amber_home_assistant_price_spike"

SOLCAST_REMAINING_TODAY = "sensor.solcast_pv_forecast_forecast_remaining_today"
SOLCAST_TOMORROW = "sensor.solcast_pv_forecast_forecast_tomorrow"
SOLCAST_NEXT_HOUR = "sensor.solcast_pv_forecast_forecast_next_hour"
SOLCAST_THIS_HOUR = "sensor.solcast_pv_forecast_forecast_this_hour"
SOLCAST_TODAY = "sensor.solcast_pv_forecast_forecast_today"
SOLCAST_POWER_NOW = "sensor.solcast_pv_forecast_power_now"

GOODWE_BATTERY_SOC = "sensor.outside_back_goodwe_inverter_battery_state_of_charge"
GOODWE_BATTERY_POWER = "sensor.outside_back_goodwe_inverter_battery_power"
GOODWE_BATTERY_MODE = "sensor.outside_back_goodwe_inverter_battery_mode"
GOODWE_PV_POWER = "sensor.outside_back_goodwe_inverter_pv_power"
GOODWE_HOUSE_CONSUMPTION = "sensor.outside_back_goodwe_inverter_house_consumption"
GOODWE_GRID_POWER = "sensor.outside_back_goodwe_inverter_meter_active_power_total"
GOODWE_WORK_MODE = "sensor.outside_back_goodwe_inverter_work_mode"

AMBER_ENTITIES = (
    AMBER_IMPORT_PRICE,
    AMBER_IMPORT_FORECAST,
    AMBER_EXPORT_PRICE,
    AMBER_EXPORT_FORECAST,
    AMBER_PRICE_SPIKE,
)
SOLCAST_REQUIRED_ENTITIES = (
    SOLCAST_REMAINING_TODAY,
    SOLCAST_TOMORROW,
    SOLCAST_NEXT_HOUR,
    SOLCAST_THIS_HOUR,
    SOLCAST_TODAY,
)
GOODWE_ENTITIES = (
    GOODWE_BATTERY_SOC,
    GOODWE_BATTERY_POWER,
    GOODWE_BATTERY_MODE,
    GOODWE_PV_POWER,
    GOODWE_HOUSE_CONSUMPTION,
    GOODWE_GRID_POWER,
    GOODWE_WORK_MODE,
)
REQUIRED_ENTITY_IDS = AMBER_ENTITIES + SOLCAST_REQUIRED_ENTITIES + GOODWE_ENTITIES
OPTIONAL_ENTITY_IDS = (SOLCAST_POWER_NOW,)
ALL_ENTITY_IDS = REQUIRED_ENTITY_IDS + OPTIONAL_ENTITY_IDS
