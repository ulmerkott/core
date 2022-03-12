"""Support for SolarEdge Monitoring API."""
from __future__ import annotations

from datetime import timedelta
from typing import Any

from solaredge import Solaredge

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    DEVICE_CLASS_BATTERY,
    DEVICE_CLASS_POWER,
    SUN_EVENT_SUNRISE,
    SUN_EVENT_SUNSET,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_sunrise, async_track_sunset
from homeassistant.helpers.sun import get_astral_event_next, is_up
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util.dt import utcnow

from .const import (
    CONF_SITE_ID,
    DATA_API_CLIENT,
    DETAILS_DAILY_UPDATE_LIMIT,
    DOMAIN,
    ENERGY_DETAILS_DAILY_UPDATE_LIMIT,
    INVENTORY_DAILY_UPDATE_LIMIT,
    LIMIT_WHILE_DAYLIGHT_RATIO,
    OVERVIEW_DAILY_UPDATE_LIMIT,
    POWER_FLOW_DAILY_UPDATE_LIMIT,
    SENSOR_TYPES,
)
from .coordinator import (
    SolarEdgeDataService,
    SolarEdgeDetailsDataService,
    SolarEdgeEnergyDetailsService,
    SolarEdgeInventoryDataService,
    SolarEdgeOverviewDataService,
    SolarEdgePowerFlowDataService,
)
from .models import SolarEdgeSensorEntityDescription


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add an solarEdge entry."""
    # Add the needed sensors to hass
    api: Solaredge = hass.data[DOMAIN][entry.entry_id][DATA_API_CLIENT]

    sensor_factory = SolarEdgeSensorFactory(
        hass, entry.title, entry.data[CONF_SITE_ID], api
    )

    # Set initial update interval based on current daylight condition.
    daylight = is_up(hass, utcnow())
    duration = await sensor_factory.get_event_duration(
        SUN_EVENT_SUNSET if daylight else SUN_EVENT_SUNRISE
    )
    for service in sensor_factory.all_services:
        service.async_setup()
        await service.recalculate_update_interval(duration, daylight)
        await service.coordinator.async_refresh()

    entities = []
    for sensor_type in SENSOR_TYPES:
        sensor = sensor_factory.create_sensor(sensor_type)
        if sensor is not None:
            entities.append(sensor)
    async_add_entities(entities)


class SolarEdgeSensorFactory:
    """Factory which creates sensors based on the sensor_key."""

    def __init__(
        self, hass: HomeAssistant, platform_name: str, site_id: str, api: Solaredge
    ) -> None:
        """Initialize the factory."""
        self.platform_name = platform_name

        details = SolarEdgeDetailsDataService(
            hass, api, site_id, DETAILS_DAILY_UPDATE_LIMIT
        )
        overview = SolarEdgeOverviewDataService(
            hass, api, site_id, OVERVIEW_DAILY_UPDATE_LIMIT, LIMIT_WHILE_DAYLIGHT_RATIO
        )
        inventory = SolarEdgeInventoryDataService(
            hass, api, site_id, INVENTORY_DAILY_UPDATE_LIMIT
        )
        flow = SolarEdgePowerFlowDataService(
            hass,
            api,
            site_id,
            POWER_FLOW_DAILY_UPDATE_LIMIT,
            LIMIT_WHILE_DAYLIGHT_RATIO,
        )
        energy = SolarEdgeEnergyDetailsService(
            hass,
            api,
            site_id,
            ENERGY_DETAILS_DAILY_UPDATE_LIMIT,
            LIMIT_WHILE_DAYLIGHT_RATIO,
        )

        self.hass = hass
        self.all_services = (details, overview, inventory, flow, energy)

        async_track_sunrise(hass, self.sunrise_callback)
        async_track_sunset(hass, self.sunset_callback)

        self.services: dict[
            str,
            tuple[
                type[SolarEdgeSensorEntity | SolarEdgeOverviewSensor],
                SolarEdgeDataService,
            ],
        ] = {"site_details": (SolarEdgeDetailsSensor, details)}

        for key in (
            "lifetime_energy",
            "energy_this_year",
            "energy_this_month",
            "energy_today",
            "current_power",
        ):
            self.services[key] = (SolarEdgeOverviewSensor, overview)

        for key in ("meters", "sensors", "gateways", "batteries", "inverters"):
            self.services[key] = (SolarEdgeInventorySensor, inventory)

        for key in ("power_consumption", "solar_power", "grid_power", "storage_power"):
            self.services[key] = (SolarEdgePowerFlowSensor, flow)

        for key in ("storage_level",):
            self.services[key] = (SolarEdgeStorageLevelSensor, flow)

        for key in (
            "purchased_energy",
            "production_energy",
            "feedin_energy",
            "consumption_energy",
            "selfconsumption_energy",
        ):
            self.services[key] = (SolarEdgeEnergyDetailsSensor, energy)

    def create_sensor(
        self, sensor_type: SolarEdgeSensorEntityDescription
    ) -> SolarEdgeSensorEntityDescription:
        """Create and return a sensor based on the sensor_key."""
        sensor_class, service = self.services[sensor_type.key]

        return sensor_class(self.platform_name, sensor_type, service)

    async def get_event_duration(self, event) -> timedelta:
        """Get duration for the next astral event."""
        return get_astral_event_next(self.hass, event) - utcnow()

    @callback
    async def sunset_callback(self):
        """Call for sunset astral event."""
        duration = await self.get_event_duration(SUN_EVENT_SUNSET)
        await self.recalculate_update_intervals(duration, daylight=False)

    @callback
    async def sunrise_callback(self):
        """Call for sunrise astral event."""
        duration = await self.get_event_duration(SUN_EVENT_SUNRISE)
        await self.recalculate_update_intervals(duration, daylight=True)

    async def recalculate_update_intervals(self, duration: timedelta, daylight: bool):
        """Go through all services and refresh the update_interval based on current conditions."""
        for service in self.all_services:
            await service.recalculate_update_interval(duration, daylight)
            await service.coordinator.async_refresh()


class SolarEdgeSensorEntity(CoordinatorEntity, SensorEntity):
    """Abstract class for a solaredge sensor."""

    entity_description: SolarEdgeSensorEntityDescription

    def __init__(
        self,
        platform_name: str,
        description: SolarEdgeSensorEntityDescription,
        data_service: SolarEdgeDataService,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(data_service.coordinator)
        self.platform_name = platform_name
        self.entity_description = description
        self.data_service = data_service

        self._attr_name = f"{platform_name} ({description.name})"

    @property
    def unique_id(self) -> str | None:
        """Return a unique ID."""
        if not self.data_service.site_id:
            return None
        return f"{self.data_service.site_id}_{self.entity_description.key}"


class SolarEdgeOverviewSensor(SolarEdgeSensorEntity):
    """Representation of an SolarEdge Monitoring API overview sensor."""

    @property
    def native_value(self) -> str | None:
        """Return the state of the sensor."""
        return self.data_service.data.get(self.entity_description.json_key)


class SolarEdgeDetailsSensor(SolarEdgeSensorEntity):
    """Representation of an SolarEdge Monitoring API details sensor."""

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the state attributes."""
        return self.data_service.attributes

    @property
    def native_value(self) -> str | None:
        """Return the state of the sensor."""
        return self.data_service.data

    @property
    def unique_id(self) -> str | None:
        """Return a unique ID."""
        if not self.data_service.site_id:
            return None
        return f"{self.data_service.site_id}"


class SolarEdgeInventorySensor(SolarEdgeSensorEntity):
    """Representation of an SolarEdge Monitoring API inventory sensor."""

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the state attributes."""
        return self.data_service.attributes.get(self.entity_description.json_key)

    @property
    def native_value(self) -> str | None:
        """Return the state of the sensor."""
        return self.data_service.data.get(self.entity_description.json_key)


class SolarEdgeEnergyDetailsSensor(SolarEdgeSensorEntity):
    """Representation of an SolarEdge Monitoring API power flow sensor."""

    def __init__(self, platform_name, sensor_type, data_service):
        """Initialize the power flow sensor."""
        super().__init__(platform_name, sensor_type, data_service)

        self._attr_native_unit_of_measurement = data_service.unit

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the state attributes."""
        return self.data_service.attributes.get(self.entity_description.json_key)

    @property
    def native_value(self) -> str | None:
        """Return the state of the sensor."""
        return self.data_service.data.get(self.entity_description.json_key)


class SolarEdgePowerFlowSensor(SolarEdgeSensorEntity):
    """Representation of an SolarEdge Monitoring API power flow sensor."""

    _attr_device_class = SensorDeviceClass.POWER

    def __init__(
        self,
        platform_name: str,
        description: SolarEdgeSensorEntityDescription,
        data_service: SolarEdgeDataService,
    ) -> None:
        """Initialize the power flow sensor."""
        super().__init__(platform_name, description, data_service)

        self._attr_native_unit_of_measurement = data_service.unit

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the state attributes."""
        return self.data_service.attributes.get(self.entity_description.json_key)

    @property
    def native_value(self) -> str | None:
        """Return the state of the sensor."""
        return self.data_service.data.get(self.entity_description.json_key)


class SolarEdgeStorageLevelSensor(SolarEdgeSensorEntity):
    """Representation of an SolarEdge Monitoring API storage level sensor."""

    _attr_device_class = SensorDeviceClass.BATTERY

    @property
    def native_value(self) -> str | None:
        """Return the state of the sensor."""
        attr = self.data_service.attributes.get(self.entity_description.json_key)
        if attr and "soc" in attr:
            return attr["soc"]
        return None
