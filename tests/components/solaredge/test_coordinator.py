"""Tests for the SolarEdge coordinator services."""
from datetime import timedelta
from unittest.mock import Mock, patch

import pytest

from homeassistant.components.solaredge.coordinator import SolarEdgeDataService
from homeassistant.core import HomeAssistant

SITE_ID = "1a2b3c4d5e6f7g8h"
DAYLIGHT_LIMIT_RATIO = 0.9
DAILY_LIMIT = 100
DAYLIGHT_LIMIT = 90
DARK_LIMIT = 10
DAY_DURATION = timedelta(days=1)


@patch("homeassistant.helpers.update_coordinator.DataUpdateCoordinator")
async def test_data_service(hass: HomeAssistant) -> None:
    """Test data service."""
    DAYLIGHT_DURATION = timedelta(minutes=500)
    DARK_DURATION = timedelta(minutes=940)

    data_service = SolarEdgeDataService(
        hass, Mock(), SITE_ID, DAILY_LIMIT, DAYLIGHT_LIMIT_RATIO
    )
    data_service.async_setup()
    # Default interval should be distributed over the whole day
    assert data_service.coordinator.update_interval == (DAY_DURATION / DAILY_LIMIT)

    # Calculate update interval based on daylight
    await data_service.recalculate_update_interval(DAYLIGHT_DURATION, daylight=True)
    assert (
        data_service.coordinator.update_interval == DAYLIGHT_DURATION / DAYLIGHT_LIMIT
    )

    # Check that we are within the daily limit budget
    daylight_update_count = round(
        DAYLIGHT_DURATION / data_service.coordinator.update_interval, ndigits=5
    )
    assert daylight_update_count <= DAYLIGHT_LIMIT

    # Calculate update interval based on dark period
    await data_service.recalculate_update_interval(DARK_DURATION, daylight=False)
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
    data_service = SolarEdgeDataService(
        hass, Mock(), SITE_ID, DAILY_LIMIT, DAYLIGHT_LIMIT_RATIO
    )
    data_service.async_setup()
    # Default interval should be distributed over the whole day
    assert data_service.coordinator.update_interval == (DAY_DURATION / DAILY_LIMIT)

    # Calculate update interval based all day or zero length daylight. Should ignore the RATIO and use DAILY_LIMIT.
    await data_service.recalculate_update_interval(DAYLIGHT_DURATION, daylight=True)
    assert data_service.coordinator.update_interval == DAY_DURATION / DAILY_LIMIT

    # Check that we are within the daily limit budget
    assert (
        round(DAY_DURATION / data_service.coordinator.update_interval, ndigits=5)
        <= DAILY_LIMIT
    )

    # Calculate update interval based all day or zero length dark period. Should ignore the RATIO and use DAILY_LIMIT.
    await data_service.recalculate_update_interval(DARK_DURATION, daylight=False)
    assert data_service.coordinator.update_interval == DAY_DURATION / DAILY_LIMIT

    # Check that we are within the dark limit budget
    assert (
        round(DAY_DURATION / data_service.coordinator.update_interval, ndigits=5)
        <= DAILY_LIMIT
    )
