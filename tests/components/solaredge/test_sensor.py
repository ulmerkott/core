"""Tests for the SolarEdge coordinator services."""
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

from homeassistant.components.solaredge.const import (
    CONF_DYNAMIC_UPDATE_INTERVAL,
    CONF_SITE_ID,
    DATA_API_CLIENT,
    DEFAULT_NAME,
    DOMAIN,
)
import homeassistant.components.solaredge.sensor as sensor
from homeassistant.const import (
    CONF_API_KEY,
    CONF_NAME,
    SUN_EVENT_SUNRISE,
    SUN_EVENT_SUNSET,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.sun import get_astral_event_date
import homeassistant.util.dt as dt_util

from tests.common import MockConfigEntry

NAME = "solaredge site 1 2 3"
SITE_ID = "1a2b3c4d5e6f7g8h"
API_KEY = "a1b2c3d4e5f6g7h8"
DAY_DURATION = timedelta(days=1)


@patch(
    "homeassistant.components.solaredge.coordinator.SolarEdgeDataService.recalculate_update_interval"
)
@patch("homeassistant.components.solaredge.sensor.utcnow")
async def test_async_setup_entry(utcnow, recalc, hass: HomeAssistant) -> None:
    """Test that async_setup_entry is initializing coordinator services correctly."""
    config_entry = MockConfigEntry(
        domain="solaredge",
        data={
            CONF_NAME: DEFAULT_NAME,
            CONF_SITE_ID: SITE_ID,
            CONF_API_KEY: API_KEY,
            CONF_DYNAMIC_UPDATE_INTERVAL: False,
        },
    )
    config_entry.add_to_hass(hass)
    hass.data.setdefault(DOMAIN, {})[config_entry.entry_id] = {
        DATA_API_CLIENT: MagicMock()
    }

    # recalculate_update_interval should not be called when CONF_DYNAMIC_UPDATE_INTERVAL is False
    utcnow.return_value = datetime(2021, 10, 30, 12, 10, tzinfo=dt_util.UTC)
    await sensor.async_setup_entry(hass, config_entry, MagicMock())
    recalc.assert_not_called()


@patch(
    "homeassistant.components.solaredge.coordinator.SolarEdgeDataService.recalculate_update_interval"
)
@patch("homeassistant.components.solaredge.sensor.async_track_sunrise")
@patch("homeassistant.components.solaredge.sensor.async_track_sunset")
@patch("homeassistant.components.solaredge.sensor.utcnow")
async def test_async_setup_entry_dynamic_update_interval(
    utcnow, sunset, sunrise, recalc, hass: HomeAssistant
) -> None:
    """Test that async_setup_entry is initializing coordinator services correctly."""

    # Set location to up north where sun doesn't always set/rise
    hass.config.latitude = 69.0596
    hass.config.longitude = 20.5483

    config_entry = MockConfigEntry(
        domain="solaredge",
        data={
            CONF_NAME: DEFAULT_NAME,
            CONF_SITE_ID: SITE_ID,
            CONF_API_KEY: API_KEY,
            CONF_DYNAMIC_UPDATE_INTERVAL: True,
        },
    )
    config_entry.add_to_hass(hass)
    hass.data.setdefault(DOMAIN, {})[config_entry.entry_id] = {
        DATA_API_CLIENT: MagicMock()
    }

    # Check that middle of the day returns duration for current day events.
    middle_of_the_day = datetime(2021, 10, 30, 12, 24, tzinfo=dt_util.UTC)
    utcnow.return_value = middle_of_the_day
    expected_duration = get_astral_event_date(
        hass, SUN_EVENT_SUNSET, date=middle_of_the_day
    ) - get_astral_event_date(hass, SUN_EVENT_SUNRISE, date=middle_of_the_day)
    await sensor.async_setup_entry(hass, config_entry, MagicMock())
    recalc.assert_called_with(expected_duration, daylight=True)

    # Check that time after sunset returns duration for current day sunset until next day sunrise.
    after_dark = datetime(2021, 10, 30, 21, 24, tzinfo=dt_util.UTC)
    utcnow.return_value = after_dark
    expected_duration = get_astral_event_date(
        hass, SUN_EVENT_SUNRISE, date=after_dark + timedelta(days=1)
    ) - get_astral_event_date(hass, SUN_EVENT_SUNSET, date=after_dark)
    await sensor.async_setup_entry(hass, config_entry, MagicMock())
    recalc.assert_called_with(expected_duration, daylight=False)

    # Check that time before sunrise returns duration for previous day sunset until current day sunrise.
    before_daylight = datetime(2021, 10, 30, 4, 24, tzinfo=dt_util.UTC)
    utcnow.return_value = before_daylight
    expected_duration = get_astral_event_date(
        hass, SUN_EVENT_SUNRISE, date=before_daylight
    ) - get_astral_event_date(
        hass, SUN_EVENT_SUNSET, date=before_daylight - timedelta(days=1)
    )
    await sensor.async_setup_entry(hass, config_entry, MagicMock())
    recalc.assert_called_with(expected_duration, daylight=False)

    # Dark the whole day should use whole day as duration
    utcnow.return_value = datetime(2022, 1, 1, 12, 24, tzinfo=dt_util.UTC)
    await sensor.async_setup_entry(hass, config_entry, MagicMock())
    recalc.assert_called_with(DAY_DURATION, daylight=False)

    # Daylight the whole day should use whole day as duration
    utcnow.return_value = datetime(2022, 6, 20, 15, 00, tzinfo=dt_util.UTC)
    await sensor.async_setup_entry(hass, config_entry, MagicMock())
    recalc.assert_called_with(DAY_DURATION, daylight=True)
