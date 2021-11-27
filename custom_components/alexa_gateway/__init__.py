import requests
import json
import logging
from datetime import datetime, timedelta
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.helpers.typing import ConfigType
from homeassistant.exceptions import HomeAssistantError
from homeassistant.const import (
    CONF_ENTITY_ID, CONF_ACCESS_TOKEN, CONF_STATE, CONF_URL,
    MATCH_ALL, CONF_CLIENT_ID, CONF_CLIENT_SECRET,
    ATTR_FRIENDLY_NAME)
from .alexa_response import AlexaResponse

COMPONENT_DOMAIN = "alexa_gateway"
CONF_AUTH_URL = "auth_url"
DEFAULT_TOKEN_CACHE = "/share/.alexa-gateway.token"
_LOGGER = logging.getLogger(__name__)

ATTR_MANUFACTURER = "Green Olive Smart Home"
ATTR_DESCRIPTION = "Home-Assistant Device"


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    @callback
    async def report_state(call: ServiceCall) -> None:
        url = config[COMPONENT_DOMAIN].get(CONF_AUTH_URL)
        token = await get_token(hass,
                                config[COMPONENT_DOMAIN].get(
                                    CONF_AUTH_URL),
                                config[COMPONENT_DOMAIN].get(
                                    CONF_CLIENT_ID),
                                config[COMPONENT_DOMAIN].get(CONF_CLIENT_SECRET))
        entity_id = call.data.get(CONF_ENTITY_ID)
        new_state = call.data.get(CONF_STATE)
        await hass.async_add_executor_job(post_gateway, url, token, entity_id, new_state)

    hass.services.async_register(COMPONENT_DOMAIN,
                                 "report_state",
                                 report_state)

    @callback
    async def process_request(call: ServiceCall) -> None:
        _LOGGER.debug("Alexa request: %s", call.data)
        name = call.data["directive"]["header"]["name"]
        namespace = call.data["directive"]["header"]["namespace"]

        if namespace == "Alexa.Authorization" and name == "AcceptGrant":
            # Use grant code to get first auth token
            code = call.data["directive"]["payload"]["grant"]["code"]
            await get_token(hass,
                            config[COMPONENT_DOMAIN].get(CONF_AUTH_URL),
                            config[COMPONENT_DOMAIN].get(CONF_CLIENT_ID),
                            config[COMPONENT_DOMAIN].get(CONF_CLIENT_SECRET),
                            code)

        elif namespace == "Alexa.Discovery":
            token = await get_token(hass,
                                    config[COMPONENT_DOMAIN].get(
                                        CONF_AUTH_URL),
                                    config[COMPONENT_DOMAIN].get(
                                        CONF_CLIENT_ID),
                                    config[COMPONENT_DOMAIN].get(CONF_CLIENT_SECRET))
            response = await discovery_handler(hass, call.data)
            response["event"]["payload"]["scope"]["token"] = token
            _LOGGER.debug(response)
            await hass.async_add_executor_job(post_gateway,
                                              config[COMPONENT_DOMAIN].get(
                                                  CONF_URL),
                                              token,
                                              response)

    #  elif name == "ReportState":
    #    # Call home-assistant
    #    response = get_status(request)
    #    # Get auth token and send response to alexa gateway
    #    token = get_token()
    #    response["event"]["endpoint"]["scope"]["token"] = token
    #    logger.info("Token retrieved, sending change state response back to Alexa gateway...")
    #    logger.info(json.dumps(response))
    #    send_event(token, response)

        else:
            token = await get_token(hass,
                                    config[COMPONENT_DOMAIN].get(
                                        CONF_AUTH_URL),
                                    config[COMPONENT_DOMAIN].get(
                                        CONF_CLIENT_ID),
                                    config[COMPONENT_DOMAIN].get(CONF_CLIENT_SECRET))
            response = await service_handler(hass, call.data)
            response["event"]["endpoint"]["scope"]["token"] = token
            _LOGGER.debug(response)
            await hass.async_add_executor_job(post_gateway,
                                              config[COMPONENT_DOMAIN].get(
                                                  CONF_URL),
                                              token,
                                              response)

    hass.services.async_register(COMPONENT_DOMAIN,
                                 "process_request",
                                 process_request)

    return True


async def discovery_handler(hass, request):
    # Prepare the Alexa response
    adr = AlexaResponse(namespace="Alexa.Discovery", name="AddOrUpdateReport",
                        payload={"scope": {"type": "BearerToken", "token": ""}})

    # Each domain represents a specific Alexa capability
    capability_alexa = adr.create_payload_endpoint_capability()
    capability_switch = adr.create_payload_endpoint_capability(
        interface="Alexa.PowerController",
        supported=[{"name": "powerState"}],
        retrievable=False,
        proactively_reported=True)
    capability_dimmer = adr.create_payload_endpoint_capability(
        interface="Alexa.BrightnessController",
        supported=[{"name": "brightness"}],
        retrievable=False,
        proactively_reported=True)
    capability_thermostat = adr.create_payload_endpoint_capability(
        interface="Alexa.ThermostatController",
        supported=[{"name": "lowerSetpoint"},
                   {"name": "upperSetpoint"},
                   {"name": "thermostatMode"}],
        retrievable=False,
        proactively_reported=True,
        supported_modes=["HEAT", "COOL", "AUTO", "OFF"])
    capability_temperature = adr.create_payload_endpoint_capability(
        interface="Alexa.TemperatureSensor",
        retrievable=False,
        proactively_reported=True,
        supported=[{"name": "temperature"}])
    capability_contact = adr.create_payload_endpoint_capability(
        interface="Alexa.ContactSensor",
        retrievable=False,
        proactively_reported=True,
        supported=[{"name": "detectionState"}])

    # Map entities to alexa endpoints
    entities = hass.states.async_entity_ids()
    for entity in entities:
        domain = entity.split(".")[0]
        state = hass.states.get(entity)

        if domain in ["light"]:
            adr.add_payload_endpoint(
                endpoint_id=entity,
                friendly_name=state.attributes.get(ATTR_FRIENDLY_NAME),
                description=ATTR_DESCRIPTION,
                manufacturer_name=ATTR_MANUFACTURER,
                display_categories=["LIGHT"],
                capabilities=[capability_alexa, capability_switch, capability_dimmer])

        if domain in ["switch", "script", "input_boolean"]:
            adr.add_payload_endpoint(
                endpoint_id=entity,
                friendly_name=state.attributes.get(ATTR_FRIENDLY_NAME),
                description=ATTR_DESCRIPTION,
                manufacturer_name=ATTR_MANUFACTURER,
                display_categories=["SWITCH"],
                capabilities=[capability_alexa, capability_switch])

        if domain in ["climate"]:
            adr.add_payload_endpoint(
                endpoint_id=entity,
                friendly_name=state.attributes.get(ATTR_FRIENDLY_NAME),
                description=ATTR_DESCRIPTION,
                manufacturer_name=ATTR_MANUFACTURER,
                display_categories=["THERMOSTAT"],
                capabilities=[capability_alexa, capability_thermostat, capability_temperature])

        if domain in ["sensor"]:
            adr.add_payload_endpoint(
                endpoint_id=entity,
                friendly_name=state.attributes.get(ATTR_FRIENDLY_NAME),
                description=ATTR_DESCRIPTION,
                manufacturer_name=ATTR_MANUFACTURER,
                display_categories=["CONTACT_SENSOR"],
                capabilities=[capability_alexa, capability_contact])

    return adr.get()

    # TO-DO in case of an error
    # except Exception as err:
    #logger.info("Home-assistant call failed, because %s", str(err))
    # return AlexaResponse(name="ErrorResponse",
    #            payload={"type": "ENDPOINT_UNREACHABLE", "message": str(err)}).get()


async def service_handler(hass, request):
    # Extract Alexa request values and map to Home-Assistant
    name = request["directive"]["header"]["name"]
    namespace = request["directive"]["header"]["namespace"]
    correlation_token = request["directive"]["header"]["correlationToken"]
    scope_token = request["directive"]["endpoint"]["scope"]["token"]
    entity_id = request["directive"]["endpoint"]["endpointId"]
    domain = entity_id.split(".")[0]

    if namespace == "Alexa.PowerController":
        property_name = "powerState"
        if name == "TurnOff":
            service = "turn_off"
            property_value = "OFF"
        else:
            service = "turn_on"
            property_value = "ON"
            payload = {"entity_id": entity_id}

    if namespace == "Alexa.BrightnessController":
        property_name = "brightness"
        property_value = request["directive"]["payload"]["brightness"]
        service = "turn_on"
        payload = {"entity_id": entity_id,
                   "brightness_pct": property_value}

    if namespace == "Alexa.ThermostatController" and name == "AdjustTargetTemperature":
        domain = "script"
        service = "climate_adjust"
        property_value = request["directive"]["payload"]["targetSetpointDelta"]["value"]
        payload = {"entity": entity_id,
                   "temp_delta": property_value}
        property_name = "targetSetpoint"
        property_value = {"value": property_value, "scale": "FAHRENHEIT"}

    # Call HASS Service
    await hass.services.async_call(domain, service, payload)

    # TO-DO: Retrieve HASS status and send to Alexa gateway

    # Return an Alexa reponse
    alexa_response = AlexaResponse(correlation_token=correlation_token,
                                   scope_token=scope_token,
                                   endpoint_id=entity_id)
    alexa_response.add_context_property(namespace=namespace,
                                        name=property_name,
                                        value=property_value)
    return alexa_response.get()


def post_gateway(url, token, payload):
    try:
        headers = {"Authorization": "Bearer {}".format(token),
                   "Content-Type": "application/json;charset=UTF-8"}
        response = requests.post(url, headers=headers, json=payload)
        response.raise_for_status()
        _LOGGER.info("Alexa async message post sent, code %s %s",
                     str(response.status_code), response.text)
    except Exception as err:
        _LOGGER.error(
            "Failed to send event to Alexa gateway because %s %s", str(err), response.text)
        raise err


async def get_token(hass, url, client_id, client_secret, code=None):
    cfg = await hass.async_add_executor_job(read_config, DEFAULT_TOKEN_CACHE)

    dt = datetime.now()
    if code is not None:
        _LOGGER.debug("First time auth, need new token...")
        token, refresh = await hass.async_add_executor_job(grant_token, url, client_id, client_secret, code)
        cfg["access_token"] = token
        cfg["refresh_token"] = refresh
        cfg["expiration"] = str(dt + timedelta(seconds=3600))
        await hass.async_add_executor_job(write_config, DEFAULT_TOKEN_CACHE, cfg)
    elif cfg["expiration"] < str(dt):
        _LOGGER.debug("Token expired, refreshing token...")
        token, refresh = await hass.async_add_executor_job(refresh_token, url, client_id, client_secret, cfg["refresh_token"])
        cfg["access_token"] = token
        cfg["refresh_token"] = refresh
        cfg["expiration"] = str(dt + timedelta(seconds=3600))
        await hass.async_add_executor_job(write_config, DEFAULT_TOKEN_CACHE, cfg)
    else:
        token = cfg["access_token"]
    return token


def grant_token(url, client_id, client_secret, code):
    try:
        headers = {
            "content-type": "application/x-www-form-urlencoded;charset=UTF-8"}
        payload = "grant_type=authorization_code&code={}&client_id={}&client_secret={}".format(
            code, client_id, client_secret)
        _LOGGER.debug(payload)
        response = requests.post(url, headers=headers, data=payload)
        response.raise_for_status()
        payload = response.json()
        return payload["access_token"], payload["refresh_token"]
    except Exception as err:
        _LOGGER.error("Failed to grant token because %s", str(err))


def refresh_token(url, client_id, client_secret, token):
    try:
        headers = {
            "content-type": "application/x-www-form-urlencoded;charset=UTF-8"}
        payload = "grant_type=refresh_token&refresh_token={}&client_id={}&client_secret={}".format(
            token, client_id, client_secret)
        _LOGGER.debug(payload)
        response = requests.post(url, headers=headers, data=payload)
        response.raise_for_status()
        payload = response.json()
        return payload["access_token"], payload["refresh_token"]
    except Exception as err:
        _LOGGER.error("Failed to refresh token, because %s", str(err))


def read_config(filename):
    try:
        with open(filename, "r") as f:
            return json.load(f)
    except IOError as ex:
        _LOGGER.error("Failed to read configuration file, because %s", ex)


def write_config(filename, config):
    try:
        with open(filename, "w") as f:
            json.dump(config, f)
    except IOError as ex:
        _LOGGER.error("Failed to write configuration file, because %s", ex)


def changereport_payload(token, endpoint_id, value):
    data = {
        "event": {
            "header": {
                "namespace": "Alexa",
                "name": "ChangeReport",
                "messageId": "1234567890",
                "payloadVersion": "3"
            },
            "endpoint": {
                "scope": {
                    "type": "BearerToken",
                    "token": token
                },
                "endpointId": endpoint_id
            },
            "payload": {
                "change": {
                    "cause": {
                        "type": "PHYSICAL_INTERACTION"
                    },
                    "properties": [
                        {
                            "namespace": "Alexa.ContactSensor",
                            "name": "detectionState",
                            "value": value,
                            "timeOfSample": datetime.now().astimezone().isoformat(),
                            "uncertaintyInMilliseconds": 0
                        }
                    ]
                }
            }
        }
    }
    return data
