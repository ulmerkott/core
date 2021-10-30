"""Provides the data update coordinators for SolarEdge."""
from __future__ import annotations

from abc import abstractmethod
from datetime import date, datetime, timedelta

from solaredge import Solaredge
from stringcase import snakecase

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import LOGGER


class SolarEdgeDataService:
    """Get and update the latest data."""

    def __init__(
        self,
        hass: HomeAssistant,
        api: Solaredge,
        site_id: str,
        daily_update_limit: int,
        daylight_update_limit_ratio: float | None = None,
    ) -> None:
        """Initialize the data object."""
        self.api = api
        self.site_id = site_id

        self.data = {}
        self.attributes = {}

        self.hass = hass
        self.coordinator = None

        self.daily_update_limit = daily_update_limit
        self.daylight_update_limit_ratio = daylight_update_limit_ratio

        # Set default update limit. This will be modified dynamically based on daylight for if self.daylight_update_limit_percentage is not None.
        self.current_update_interval = timedelta(days=1) / self.daily_update_limit

    @callback
    def async_setup(self) -> None:
        """Coordinator creation."""
        self.coordinator = DataUpdateCoordinator(
            self.hass,
            LOGGER,
            name=str(self),
            update_method=self.async_update_data,
            update_interval=self.current_update_interval,
        )

    @abstractmethod
    def update(self) -> None:
        """Update data in executor."""

    async def recalculate_update_interval(
        self, duration: timedelta, daylight: bool
    ) -> None:
        """Recalculate update_interval based on available daylight."""

        # Only alter update_interval for services that uses daylight_update_limit_percentage
        if not self.daylight_update_limit_ratio:
            return

        # If duration is zero or whole day, ignore the ratio and use daily limit instead.
        if duration == timedelta(days=1) or duration == timedelta(0):
            self.current_update_interval = timedelta(days=1) / self.daily_update_limit
        else:
            if daylight:
                update_limit = round(
                    self.daylight_update_limit_ratio * self.daily_update_limit,
                    ndigits=5,
                )
            else:
                update_limit = round(
                    (1 - self.daylight_update_limit_ratio) * self.daily_update_limit,
                    ndigits=5,
                )
            self.current_update_interval = duration / update_limit

        self.coordinator.update_interval = self.current_update_interval
        LOGGER.debug(
            f"Recalculated update interval={self.current_update_interval} for daylight={daylight} duration={duration}"
        )

    async def async_update_data(self) -> None:
        """Update data."""
        await self.hass.async_add_executor_job(self.update)


class SolarEdgeOverviewDataService(SolarEdgeDataService):
    """Get and update the latest overview data."""

    def update(self) -> None:
        """Update the data from the SolarEdge Monitoring API."""
        try:
            data = self.api.get_overview(self.site_id)
            overview = data["overview"]
        except KeyError as ex:
            raise UpdateFailed("Missing overview data, skipping update") from ex

        self.data = {}

        for key, value in overview.items():
            if key in ["lifeTimeData", "lastYearData", "lastMonthData", "lastDayData"]:
                data = value["energy"]
            elif key in ["currentPower"]:
                data = value["power"]
            else:
                data = value
            self.data[key] = data

        LOGGER.debug("Updated SolarEdge overview: %s", self.data)


class SolarEdgeDetailsDataService(SolarEdgeDataService):
    """Get and update the latest details data."""

    def __init__(
        self,
        hass: HomeAssistant,
        api: Solaredge,
        site_id: str,
        daily_update_limit: int,
        daylight_update_limit_percentage: float | None = None,
    ) -> None:
        """Initialize the details data service."""
        super().__init__(
            hass, api, site_id, daily_update_limit, daylight_update_limit_percentage
        )

        self.data = None

    def update(self) -> None:
        """Update the data from the SolarEdge Monitoring API."""
        try:
            data = self.api.get_details(self.site_id)
            details = data["details"]
        except KeyError as ex:
            raise UpdateFailed("Missing details data, skipping update") from ex

        self.data = None
        self.attributes = {}

        for key, value in details.items():
            key = snakecase(key)

            if key in ["primary_module"]:
                for module_key, module_value in value.items():
                    self.attributes[snakecase(module_key)] = module_value
            elif key in [
                "peak_power",
                "type",
                "name",
                "last_update_time",
                "installation_date",
            ]:
                self.attributes[key] = value
            elif key == "status":
                self.data = value

        LOGGER.debug("Updated SolarEdge details: %s, %s", self.data, self.attributes)


class SolarEdgeInventoryDataService(SolarEdgeDataService):
    """Get and update the latest inventory data."""

    def update(self) -> None:
        """Update the data from the SolarEdge Monitoring API."""
        try:
            data = self.api.get_inventory(self.site_id)
            inventory = data["Inventory"]
        except KeyError as ex:
            raise UpdateFailed("Missing inventory data, skipping update") from ex

        self.data = {}
        self.attributes = {}

        for key, value in inventory.items():
            self.data[key] = len(value)
            self.attributes[key] = {key: value}

        LOGGER.debug("Updated SolarEdge inventory: %s, %s", self.data, self.attributes)


class SolarEdgeEnergyDetailsService(SolarEdgeDataService):
    """Get and update the latest power flow data."""

    def __init__(
        self,
        hass: HomeAssistant,
        api: Solaredge,
        site_id: str,
        daily_update_limit: int,
        daylight_update_limit_percentage: float | None = None,
    ) -> None:
        """Initialize the power flow data service."""
        super().__init__(
            hass, api, site_id, daily_update_limit, daylight_update_limit_percentage
        )

        self.unit = None

    def update(self) -> None:
        """Update the data from the SolarEdge Monitoring API."""
        try:
            now = datetime.now()
            today = date.today()
            midnight = datetime.combine(today, datetime.min.time())
            data = self.api.get_energy_details(
                self.site_id,
                midnight,
                now.strftime("%Y-%m-%d %H:%M:%S"),
                meters=None,
                time_unit="DAY",
            )
            energy_details = data["energyDetails"]
        except KeyError as ex:
            raise UpdateFailed("Missing power flow data, skipping update") from ex

        if "meters" not in energy_details:
            LOGGER.debug(
                "Missing meters in energy details data. Assuming site does not have any"
            )
            return

        self.data = {}
        self.attributes = {}
        self.unit = energy_details["unit"]

        for meter in energy_details["meters"]:
            if "type" not in meter or "values" not in meter:
                continue
            if meter["type"] not in [
                "Production",
                "SelfConsumption",
                "FeedIn",
                "Purchased",
                "Consumption",
            ]:
                continue
            if len(meter["values"][0]) == 2:
                self.data[meter["type"]] = meter["values"][0]["value"]
                self.attributes[meter["type"]] = {"date": meter["values"][0]["date"]}

        LOGGER.debug(
            "Updated SolarEdge energy details: %s, %s", self.data, self.attributes
        )


class SolarEdgePowerFlowDataService(SolarEdgeDataService):
    """Get and update the latest power flow data."""

    def __init__(
        self,
        hass: HomeAssistant,
        api: Solaredge,
        site_id: str,
        daily_update_limit: int,
        daylight_update_limit_percentage: float | None = None,
    ) -> None:
        """Initialize the power flow data service."""
        super().__init__(
            hass, api, site_id, daily_update_limit, daylight_update_limit_percentage
        )

        self.unit = None

    def update(self) -> None:
        """Update the data from the SolarEdge Monitoring API."""
        try:
            data = self.api.get_current_power_flow(self.site_id)
            power_flow = data["siteCurrentPowerFlow"]
        except KeyError as ex:
            raise UpdateFailed("Missing power flow data, skipping update") from ex

        power_from = []
        power_to = []

        if "connections" not in power_flow:
            LOGGER.debug(
                "Missing connections in power flow data. Assuming site does not have any"
            )
            return

        for connection in power_flow["connections"]:
            power_from.append(connection["from"].lower())
            power_to.append(connection["to"].lower())

        self.data = {}
        self.attributes = {}
        self.unit = power_flow["unit"]

        for key, value in power_flow.items():
            if key in ["LOAD", "PV", "GRID", "STORAGE"]:
                self.data[key] = value["currentPower"]
                self.attributes[key] = {"status": value["status"]}

            if key in ["GRID"]:
                export = key.lower() in power_to
                self.data[key] *= -1 if export else 1
                self.attributes[key]["flow"] = "export" if export else "import"

            if key in ["STORAGE"]:
                charge = key.lower() in power_to
                self.data[key] *= -1 if charge else 1
                self.attributes[key]["flow"] = "charge" if charge else "discharge"
                self.attributes[key]["soc"] = value["chargeLevel"]

        LOGGER.debug("Updated SolarEdge power flow: %s, %s", self.data, self.attributes)
