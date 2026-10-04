"""Constants for Statens vegvesen."""

import logging
from datetime import timedelta

DOMAIN = "vegvesen"
NAME = "Statens vegvesen"
ATTRIBUTION = "Data provided by Statens vegvesen"
LOGGER = logging.getLogger(__package__)
CONF_STATION_ID = "station_id"
CONF_STATION_NAME = "station_name"
CONF_CAMERA_ID = "camera_id"
SUBENTRY_WEATHER_STATION = "weather_station"
SUBENTRY_CAMERA = "camera"
WEATHER_ITEMS_URL = (
    "https://ogckart-sn1.atlas.vegvesen.no/ogc/features/v1/collections/"
    "datex_3_1:WeatherSimple_v2/items"
)
WEATHER_UPDATE_INTERVAL = timedelta(minutes=10)
CAMERA_ITEMS_URL = (
    "https://ogckart-sn1.atlas.vegvesen.no/ogc/features/v1/collections/"
    "datex_3_1:CctvSimple_v2/items"
)
CAMERA_UPDATE_INTERVAL = timedelta(minutes=1)
IMAGE_REQUEST_TIMEOUT = 10
REQUEST_TIMEOUT = 30
