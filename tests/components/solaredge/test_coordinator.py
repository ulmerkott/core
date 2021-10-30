"""Tests for the SolarEdge coordinator services."""
from datetime import timedelta
from unittest.mock import Mock, patch

from homeassistant.components.solaredge.coordinator import SolarEdgeDataService
from homeassistant.core import HomeAssistant

SITE_ID = "1a2b3c4d5e6f7g8h"
DAYLIGHT_LIMIT_RATIO = 0.9
DAILY_LIMIT = 100
DAYLIGHT_LIMIT = 90
DARK_LIMIT = 10
DAY_DURATION = timedelta(days=1)
DAYLIGHT_DURATION = timedelta(minutes=500)  # minutes
DARK_DURATION = timedelta(minutes=940)  # minutes


@patch("homeassistant.helpers.update_coordinator", autospec=True)
async def test_data_service(hass: HomeAssistant) -> None:
    """Test data service."""
    data_service = SolarEdgeDataService(
        hass, Mock(), SITE_ID, DAILY_LIMIT, DAYLIGHT_LIMIT_RATIO
    )
    data_service.async_setup()
    # Default interval should be distributed over the whole day
    assert data_service.current_update_interval == (DAY_DURATION / DAILY_LIMIT)

    # Calculate update interval based on daylight
    await data_service.recalculate_update_interval(DAYLIGHT_DURATION, daylight=True)
    assert data_service.current_update_interval == DAYLIGHT_DURATION / DAYLIGHT_LIMIT

    # Check that we are within the daily limit budget
    assert (
        round(DAYLIGHT_DURATION / data_service.current_update_interval, ndigits=5)
        <= DAYLIGHT_LIMIT
    )

    # Calculate update interval based on dark period
    await data_service.recalculate_update_interval(DARK_DURATION, daylight=False)
    assert data_service.current_update_interval == DARK_DURATION / DARK_LIMIT

    # Check that we are within the dark limit budget
    assert (
        round(DARK_DURATION / data_service.current_update_interval, ndigits=5)
        <= DARK_LIMIT
    )
