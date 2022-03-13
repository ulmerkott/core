"""Tests for the SolarEdge coordinator services."""
from datetime import timedelta
from unittest.mock import Mock, patch

import pytest

from homeassistant.components.solaredge.const import LIMIT_WHILE_DAYLIGHT_RATIO
from homeassistant.components.solaredge.coordinator import (
    SolarEdgeDataService,
    SolarEdgeOverviewDataService,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import UpdateFailed

SITE_ID = "1a2b3c4d5e6f7g8h"
DAILY_LIMIT = 100
DAYLIGHT_LIMIT = int(DAILY_LIMIT * LIMIT_WHILE_DAYLIGHT_RATIO)
DARK_LIMIT = DAILY_LIMIT - DAYLIGHT_LIMIT
DAY_DURATION = timedelta(days=1)

mock_overview_data = {
    "overview": {
        "lifeTimeData": {"energy": 100000},
        "lastYearData": {"energy": 50000},
        "lastMonthData": {"energy": 10000},
        "lastDayData": {"energy": 0.0},
        "currentPower": {"power": 0.0},
    }
}


@patch("solaredge.Solaredge")
def test_solaredgeoverviewdataservice_valid_energy_values(mock_solaredge):
    """Test valid no exception for valid overview data."""
    data_service = SolarEdgeOverviewDataService(
        Mock(), mock_solaredge, SITE_ID, DAILY_LIMIT, True
    )

    # Valid data
    mock_solaredge.get_overview.return_value = mock_overview_data

    # No exception should be raised
    data_service.update()


@patch("solaredge.Solaredge")
def test_solaredgeoverviewdataservice_invalid_lifetime_energy(mock_solaredge):
    """Test update will be skipped for invalid energy values."""
    data_service = SolarEdgeOverviewDataService(
        Mock(), mock_solaredge, SITE_ID, DAILY_LIMIT, True
    )

    invalid_data = mock_overview_data
    # Invalid energy values, lifeTimeData energy is lower than last year, month or day.
    invalid_data["overview"]["lifeTimeData"]["energy"] = 0
    mock_solaredge.get_overview.return_value = invalid_data

    # UpdateFailed exception should be raised
    with pytest.raises(UpdateFailed):
        data_service.update()


@patch("solaredge.Solaredge")
def test_solaredgeoverviewdataservice_invalid_year_energy(mock_solaredge):
    """Test update will be skipped for invalid energy values."""
    data_service = SolarEdgeOverviewDataService(
        Mock(), mock_solaredge, SITE_ID, DAILY_LIMIT, True
    )

    invalid_data = mock_overview_data
    # Invalid energy values, lastYearData energy is lower than last month or day.
    invalid_data["overview"]["lastYearData"]["energy"] = 0
    mock_solaredge.get_overview.return_value = invalid_data

    # UpdateFailed exception should be raised
    with pytest.raises(UpdateFailed):
        data_service.update()


@patch("solaredge.Solaredge")
def test_solaredgeoverviewdataservice_valid_all_zero_energy(mock_solaredge):
    """Test update will not be skipped for valid energy values."""
    data_service = SolarEdgeOverviewDataService(
        Mock(), mock_solaredge, SITE_ID, DAILY_LIMIT, True
    )

    invalid_data = mock_overview_data
    # All zero energy values should be valid.
    invalid_data["overview"]["lifeTimeData"]["energy"] = 0.0
    invalid_data["overview"]["lastYearData"]["energy"] = 0.0
    invalid_data["overview"]["lastMonthData"]["energy"] = 0.0
    invalid_data["overview"]["lastDayData"]["energy"] = 0.0
    mock_solaredge.get_overview.return_value = invalid_data

    data_service.update()


@patch("homeassistant.helpers.update_coordinator.DataUpdateCoordinator")
async def test_data_service(hass: HomeAssistant) -> None:
    """Test data service."""
    DAYLIGHT_DURATION = timedelta(minutes=500)
    DARK_DURATION = timedelta(minutes=940)

    data_service = SolarEdgeDataService(hass, Mock(), SITE_ID, DAILY_LIMIT, True)
    data_service.async_setup()
    # Default interval should be distributed over the whole day
    assert data_service.coordinator.update_interval == (DAY_DURATION / DAILY_LIMIT)

    # Calculate update interval based on daylight
    data_service.recalculate_update_interval(DAYLIGHT_DURATION, daylight=True)
    assert (
        data_service.coordinator.update_interval == DAYLIGHT_DURATION / DAYLIGHT_LIMIT
    )

    # Check that we are within the daily limit budget
    daylight_update_count = round(
        DAYLIGHT_DURATION / data_service.coordinator.update_interval, ndigits=5
    )
    assert daylight_update_count <= DAYLIGHT_LIMIT

    # Calculate update interval based on dark period
    data_service.recalculate_update_interval(DARK_DURATION, daylight=False)
    assert data_service.coordinator.update_interval == DARK_DURATION / DARK_LIMIT

    # Check that we are within the dark limit budget
    dark_update_count = round(
        DARK_DURATION / data_service.coordinator.update_interval, ndigits=5
    )
    assert dark_update_count <= DARK_LIMIT

    # Check that the sum of both update counts is within daily limit budget
    assert (dark_update_count + daylight_update_count) <= DAILY_LIMIT


@patch("homeassistant.helpers.update_coordinator.DataUpdateCoordinator")
@pytest.mark.parametrize(
    "DAYLIGHT_DURATION,DARK_DURATION",
    [(DAY_DURATION, timedelta(0)), (timedelta(0), DAY_DURATION)],
)
async def test_data_service_no_sun_set_or_rise(
    hass: HomeAssistant, DAYLIGHT_DURATION, DARK_DURATION
) -> None:
    """Test data service when sun doesn't set or rise. In this case RATIO should be ignored."""
    data_service = SolarEdgeDataService(hass, Mock(), SITE_ID, DAILY_LIMIT, True)
    data_service.async_setup()
    # Default interval should be distributed over the whole day
    assert data_service.coordinator.update_interval == (DAY_DURATION / DAILY_LIMIT)

    # Calculate update interval based all day or zero length daylight. Should ignore the RATIO and use DAILY_LIMIT.
    data_service.recalculate_update_interval(DAYLIGHT_DURATION, daylight=True)
    assert data_service.coordinator.update_interval == DAY_DURATION / DAILY_LIMIT

    # Check that we are within the daily limit budget
    assert (
        round(DAY_DURATION / data_service.coordinator.update_interval, ndigits=5)
        <= DAILY_LIMIT
    )

    # Calculate update interval based all day or zero length dark period. Should ignore the RATIO and use DAILY_LIMIT.
    data_service.recalculate_update_interval(DARK_DURATION, daylight=False)
    data_service.coordinator.update_interval == DAY_DURATION / DAILY_LIMIT

    # Check that we are within the dark limit budget
    assert (
        round(DAY_DURATION / data_service.coordinator.update_interval, ndigits=5)
        <= DAILY_LIMIT
    )
