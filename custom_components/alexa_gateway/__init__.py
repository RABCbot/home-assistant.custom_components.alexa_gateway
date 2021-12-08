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
CONF_COUNTER = "counter"
DEFAULT_TOKEN_CACHE = "/share/.alexa-gateway.token"
_LOGGER = logging.getLogger(__name__)

ATTR_MANUFACTURER = "GreenOlive"
ATTR_DESCRIPTION = "GreenOlive Device"
ATTR_ALEXA_INTERFACE = "alexa_interface"
ATTR_ALEXA_DISPLAY = "alexa_display"


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    @callback
    async def report_change(call: ServiceCall) -> None:
        url = config[COMPONENT_DOMAIN].get(CONF_AUTH_URL)
        token = await get_token(hass,
                                url,
                                config[COMPONENT_DOMAIN].get(
                                    CONF_CLIENT_ID),
                                config[COMPONENT_DOMAIN].get(CONF_CLIENT_SECRET))
        response = await change_handler(hass, call.data.get(CONF_ENTITY_ID))
        response["event"]["endpoint"]["scope"]["token"] = token
        _LOGGER.debug("Response posted: %s", response)
        await hass.async_add_executor_job(post_gateway,
                                          config[COMPONENT_DOMAIN].get(
                                              CONF_URL),
                                          token,
                                          response)

    hass.services.async_register(COMPONENT_DOMAIN,
                                 "report_change",
                                 report_change)

    @callback
    async def process_request(call: ServiceCall) -> None:
        _LOGGER.debug("Request received: %s", call.data)
        entity_id = config[COMPONENT_DOMAIN].get(CONF_COUNTER)
        _LOGGER.debug("Incrementing counter: %s", entity_id)
        await hass.services.async_call("counter", "increment", {"entity_id": entity_id})

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
            _LOGGER.debug("Response posted: %s", response)
            url = config[COMPONENT_DOMAIN].get(CONF_URL)
            await hass.async_add_executor_job(post_gateway,
                                              url,
                                              token,
                                              response)

        elif name == "ReportState":
            token = await get_token(hass,
                                    config[COMPONENT_DOMAIN].get(
                                        CONF_AUTH_URL),
                                    config[COMPONENT_DOMAIN].get(
                                        CONF_CLIENT_ID),
                                    config[COMPONENT_DOMAIN].get(CONF_CLIENT_SECRET))
            response = await report_handler(hass, call.data)
            response["event"]["endpoint"]["scope"]["token"] = token
            _LOGGER.debug("Response posted: %s", response)
            await hass.async_add_executor_job(post_gateway,
                                              config[COMPONENT_DOMAIN].get(
                                                  CONF_URL),
                                              token,
                                              response)

        else:
            token = await get_token(hass,
                                    config[COMPONENT_DOMAIN].get(
                                        CONF_AUTH_URL),
                                    config[COMPONENT_DOMAIN].get(
                                        CONF_CLIENT_ID),
                                    config[COMPONENT_DOMAIN].get(CONF_CLIENT_SECRET))
            response = await service_handler(hass, call.data)
            response["event"]["endpoint"]["scope"]["token"] = token
            _LOGGER.debug("Response posted: %s", response)
            await hass.async_add_executor_job(post_gateway,
                                              config[COMPONENT_DOMAIN].get(
                                                  CONF_URL),
                                              token,
                                              response)

    hass.services.async_register(COMPONENT_DOMAIN,
                                 "process_request",
                                 process_request)

    return True


def get_supportedproperty(interface):
    if interface == "Alexa.ContactSensor":
        return [{"name": "detectionState"}]

    elif interface == "Alexa.MotionSensor":
        return [{"name": "detectionState"}]

    elif interface == "Alexa.TemperatureSensor":
        return [{"name": "temperature"}]

    elif interface == "Alexa.ThermostatController":
        return [{"name": "lowerSetpoint"},
                {"name": "upperSetpoint"},
                {"name": "thermostatMode"}]

    elif interface == "Alexa.PowerController":
        return [{"name": "powerState"}]

    elif interface == "Alexa.BrightnessController":
        return [{"name": "brightness"}]

    elif interface == "Alexa.DoorbellEventSource":
        return None

    else:
        return [{"name": "detectionState"}]


def get_interface(domain, attributes):
    interface = "None"
    if domain in ["light"]:
        # TO-DO: what to do with dual capabilities, like light thathave brighness and power???
        # interface = "Alexa.BrightnessController"
        interface = "Alexa.PowerController"

    if domain in ["switch", "input_boolean"]:
        interface = "Alexa.PowerController"

    if domain in ["script"]:
        interface = "Alexa.PowerController"

    if domain in ["climate"]:
        interface = "Alexa.ThermostatController"

    if domain in ["sensor", "binary_sensor"]:
        interface = "Alexa.ContactSensor"

    # Overwrite using HASS attribute
    interface = attributes.get(ATTR_ALEXA_INTERFACE, interface)
    return interface


def get_capabilities(alexa_response, attributes, domain):
    capability = alexa_response.create_payload_endpoint_capability()
    capabilities = [capability]

    interface = get_interface(domain, attributes)

    if domain in ["light"]:
        capability = alexa_response.create_payload_endpoint_capability(
            interface="Alexa.BrightnessController",
            supported=get_supportedproperty(interface),
            retrievable=True,
            proactively_reported=True)
        capabilities.append(capability)

        capability = alexa_response.create_payload_endpoint_capability(
            interface=interface,
            supported=get_supportedproperty(interface),
            retrievable=True,
            proactively_reported=True)
        capabilities.append(capability)

    if domain in ["switch", "input_boolean"]:
        capability = alexa_response.create_payload_endpoint_capability(
            interface=interface,
            supported=get_supportedproperty(interface),
            retrievable=True,
            proactively_reported=True)
        capabilities.append(capability)

    if domain in ["script"]:
        capability = alexa_response.create_payload_endpoint_capability(
            interface=interface,
            supported=get_supportedproperty(interface),
            retrievable=False,
            proactively_reported=True)
        capabilities.append(capability)

    if domain in ["climate"]:
        capability = alexa_response.create_payload_endpoint_capability(
            interface=interface,
            supported=get_supportedproperty(interface),
            supported_modes=["HEAT", "COOL", "AUTO", "OFF"],
            retrievable=False,
            proactively_reported=True)
        capabilities.append(capability)

    if domain in ["sensor", "binary_sensor"]:
        capability = alexa_response.create_payload_endpoint_capability(
            interface=interface,
            supported=get_supportedproperty(interface),
            retrievable=True,
            proactively_reported=True)
        capabilities.append(capability)

    # Fix doorbell event
    if interface == "Alexa.DoorbellEventSource":
        capabilities.pop(0)
        capabilities[0]["proactivelyReported"] = True

    return capabilities, interface


def get_display(domain, attributes):
    if domain == "light":
        default = "LIGHT"
    else:
        default = "OTHER"

    return attributes.get(ATTR_ALEXA_DISPLAY, default)


async def discovery_handler(hass, request):
    # Prepare the Alexa response
    alexa_response = AlexaResponse(namespace="Alexa.Discovery",
                                   name="AddOrUpdateReport",
                                   payload={"scope": {"type": "BearerToken", "token": ""}})

    # Append alexa endpoint for each entity
    entities = hass.states.async_entity_ids()
    for entity_id in entities:
        domain = entity_id.split(".")[0]

        state = hass.states.get(entity_id)
        capabilities, interface = get_capabilities(
            alexa_response, state.attributes, domain)
        if interface != "None":
            alexa_response.add_payload_endpoint(
                endpoint_id=entity_id,
                friendly_name=state.attributes.get(ATTR_FRIENDLY_NAME),
                description=ATTR_DESCRIPTION,
                manufacturer_name=ATTR_MANUFACTURER,
                display_categories=[get_display(domain, state.attributes)],
                capabilities=capabilities)

    return alexa_response.get()


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
        payload = {"entity_id": entity_id}
        if name == "TurnOff":
            service = "turn_off"
            property_value = "OFF"
        else:
            service = "turn_on"
            property_value = "ON"

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
        payload = {"entity_id": entity_id,
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


def get_propertyvalue(interface, state):
    if interface in ["Alexa.ContactSensor", "Alexa.MotionSensor"]:
        if state.state.lower() == "open" or state.state.lower() == "on":
            property_value = "DETECTED"
        else:
            property_value = "NOT_DETECTED"

    elif interface in ["Alexa.TemperatureSensor"]:
        property_value = {"value": state.state, "scale": "FAHRENHEIT"}

    else:
        property_value = state.state.upper()

    return property_value


async def report_handler(hass, request):
    # Extract Alexa request values and map to Home-Assistant
    correlation_token = request["directive"]["header"]["correlationToken"]
    scope_token = request["directive"]["endpoint"]["scope"]["token"]
    entity_id = request["directive"]["endpoint"]["endpointId"]
    domain = entity_id.split(".")[0]

    # Prepare Alexa reponse
    alexa_response = AlexaResponse(name="StateReport",
                                   correlation_token=correlation_token,
                                   scope_token=scope_token,
                                   endpoint_id=entity_id)

    # Retrieve HASS state
    state = hass.states.get(entity_id)

    interface = get_interface(domain, state.attributes)

    alexa_response.add_context_property(
        namespace=interface,
        name=get_supportedproperty(interface)[0]["name"],
        value=get_propertyvalue(interface, state))

    return alexa_response.get()


async def change_handler(hass, entity_id):
    # Retrieve HASS state
    state = hass.states.get(entity_id)
    domain = entity_id.split(".")[0]

    interface = get_interface(domain, state.attributes)

    supported_property = get_supportedproperty(interface)
    if supported_property:
        alexa_response = AlexaResponse(namespace="Alexa",
                                       name="ChangeReport",
                                       endpoint_id=entity_id)
        alexa_response.add_payload_property(namespace=interface,
                                            name=supported_property[0]["name"],
                                            value=get_propertyvalue(interface, state))
    else:
        alexa_response = AlexaResponse(namespace="Alexa.DoorbellEventSource",
                                       name="DoorbellPress",
                                       endpoint_id=entity_id)
        alexa_response.add_payload_timestamp()

    return alexa_response.get()


def post_gateway(url, token, payload):
    try:
        headers = {"Authorization": "Bearer {}".format(token),
                   "Content-Type": "application/json;charset=UTF-8"}
        response = requests.post(url, headers=headers, json=payload)
        response.raise_for_status()
        _LOGGER.debug("Alexa Gateway post response: %s %s",
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

