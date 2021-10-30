"""Tests for the SolarEdge coordinator services."""
from datetime import timedelta
from unittest.mock import Mock, patch

import pytest

from homeassistant.components.solaredge.coordinator import (
    SolarEdgeDataService,
    SolarEdgeOverviewDataService,
)
from homeassistant.core import HomeAssistant

NAME = "solaredge site 1 2 3"
SITE_ID = "1a2b3c4d5e6f7g8h"
DAYLIGHT_LIMIT_RATIO = 0.9
DAILY_LIMIT = 100
DAYLIGHT_LIMIT = 90
DARK_LIMIT = 10
DAY_DURATION = timedelta(days=1)
DAYLIGHT_DURATION = timedelta(minutes=500)  # minutes
DARK_DURATION = timedelta(minutes=940)  # minutes


@pytest.fixture(name="test_api")
def mock_controller():
    """Mock a successful Solaredge API."""
    api = Mock()
    api.get_details.return_value = {"details": {"status": "active"}}

    api.get_overview.return_value = {
        "overview": {
            "lastUpdateTime": "2021-10-01 12:37:47",
            "lifeTimeData": {"energy": 10000.0},
            "lastYearData": {"energy": 5000.0},
            "lastMonthData": {"energy": 500.0},
            "lastDayData": {"energy": 10.0},
            "currentPower": {"power": 1.0},
        }
    }

    with patch("solaredge.Solaredge", return_value=api):
        yield api


@patch("homeassistant.helpers.update_coordinator", autospec=True)
async def test_data_service(hass: HomeAssistant, test_api: Mock) -> None:
    """Test data service."""
    data_service = SolarEdgeDataService(
        hass, test_api, SITE_ID, DAILY_LIMIT, DAYLIGHT_LIMIT_RATIO
    )
    data_service.async_setup()
    # Default interval should be distributed over the whole day
    assert data_service.current_update_interval == (DAY_DURATION / DAILY_LIMIT)

    # Calculate update interval based on daylight
    await data_service.recalculate_update_interval(DAYLIGHT_DURATION, daylight=True)
    assert data_service.current_update_interval == DAYLIGHT_DURATION / DAYLIGHT_LIMIT

    # Check that we are within the daily limit budget.
    assert (
        round(DAYLIGHT_DURATION / data_service.current_update_interval, ndigits=5)
        <= DAYLIGHT_LIMIT
    )

    # Calculate update interval based on dark period
    await data_service.recalculate_update_interval(DARK_DURATION, daylight=False)
    assert data_service.current_update_interval == DARK_DURATION / DARK_LIMIT

    # Check that we are within the dark limit budget.
    assert (
        round(DARK_DURATION / data_service.current_update_interval, ndigits=5)
        <= DARK_LIMIT
    )


@patch("homeassistant.helpers.update_coordinator", autospec=True)
async def test_overview_data_service(hass: HomeAssistant, test_api: Mock) -> None:
    """Test overview data service."""
    overview = SolarEdgeOverviewDataService(
        hass, test_api, SITE_ID, DAILY_LIMIT, DAYLIGHT_LIMIT_RATIO
    )
    overview.async_setup()
    overview.update()
