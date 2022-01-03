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

ATTR_MANUFACTURER = "RABCBot"
ATTR_DESCRIPTION = "RABCBot SmartHome Device"
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
        if entity_id:
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
            response = await discovery_handler(hass, call.data)
            token = await get_token(hass,
                                    config[COMPONENT_DOMAIN].get(
                                        CONF_AUTH_URL),
                                    config[COMPONENT_DOMAIN].get(
                                        CONF_CLIENT_ID),
                                    config[COMPONENT_DOMAIN].get(CONF_CLIENT_SECRET))
            response["event"]["payload"]["scope"]["token"] = token
            _LOGGER.debug("Response posted: %s", response)
            url = config[COMPONENT_DOMAIN].get(CONF_URL)
            await hass.async_add_executor_job(post_gateway,
                                              url,
                                              token,
                                              response)

        elif name == "ReportState":
            response = await report_handler(hass, call.data)
            token = await get_token(hass,
                                    config[COMPONENT_DOMAIN].get(
                                        CONF_AUTH_URL),
                                    config[COMPONENT_DOMAIN].get(
                                        CONF_CLIENT_ID),
                                    config[COMPONENT_DOMAIN].get(CONF_CLIENT_SECRET))
            response["event"]["endpoint"]["scope"]["token"] = token
            _LOGGER.debug("Response posted: %s", response)
            await hass.async_add_executor_job(post_gateway,
                                              config[COMPONENT_DOMAIN].get(
                                                  CONF_URL),
                                              token,
                                              response)

        else:
            response = await service_handler(hass, call.data)
            token = await get_token(hass,
                                    config[COMPONENT_DOMAIN].get(
                                        CONF_AUTH_URL),
                                    config[COMPONENT_DOMAIN].get(
                                        CONF_CLIENT_ID),
                                    config[COMPONENT_DOMAIN].get(CONF_CLIENT_SECRET))
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

    elif interface == "Alexa.EventDetectionSensor":
        return [{"name": "humanPresenceDetectionState"}]

    elif interface == "Alexa.DoorbellEventSource":
        return None

    elif interface == "Alexa.ModeController":
        return [{"name": "mode"}]

    elif interface == "Alexa.RangeController":
        return [{"name": "rangeValue"}]

    else:
        raise Exception(f"Supported Property not implemented yet for Interface: {interface}")

def get_interfaces(domain, override):
    interfaces = []

    if not override:
        if domain in ["light"]:
            interfaces.append("Alexa.PowerController")
            interfaces.append("Alexa.BrightnessController")
            interfaces.append("Alexa")

        if domain in ["switch", "input_boolean"]:
            interfaces.append("Alexa.PowerController")
            interfaces.append("Alexa")

        if domain in ["script"]:
            interfaces.append("Alexa.PowerController")
            interfaces.append("Alexa")

        if domain in ["climate"]:
            interfaces.append("Alexa.TemperatureSensor")
            interfaces.append("Alexa.ThermostatController")
            interfaces.append("Alexa")

        if domain in ["sensor", "binary_sensor"]:
            interfaces.append("Alexa.ContactSensor")
            interfaces.append("Alexa")

        if domain in ["cover"]:
            interfaces.append("Alexa.ModeController")
            interfaces.append("Alexa")

        if domain in ["counter"]:
            interfaces.append("Alexa.RangeController")
            interfaces.append("Alexa")

    elif override == "Alexa.DoorbellEventSource":
        interfaces.append("Alexa.DoorbellEventSource")

    elif override != "None":
        interfaces.append(override)
        interfaces.append("Alexa")

    return interfaces

def get_instance(interface):
    instance = None

    if interface == "Alexa.ModeController":
        instance = "GarageDoor.Position"

    if interface == "Alexa.RangeController":
        instance = "Counter.Number"

    return instance

def get_capability(alexa_response, interface):

    if interface == "Alexa":
        capability = alexa_response.create_payload_endpoint_capability()

    elif interface == "Alexa.DoorbellEventSource":
        capability = alexa_response.create_payload_endpoint_capability(
            interface=interface,
            proactively_reported=True)

    elif interface in ["Alexa.BrightnessController", "Alexa.PowerController", "Alexa.TemperatureSensor"]:
        capability = alexa_response.create_payload_endpoint_capability(
            interface=interface,
            supported=get_supportedproperty(interface),
            retrievable=True,
            proactively_reported=True)

    elif interface == "Alexa.ContactSensor":
        capability = alexa_response.create_payload_endpoint_capability(
            interface=interface,
            supported=get_supportedproperty(interface),
            retrievable=True,
            proactively_reported=True)

    elif interface == "Alexa.MotionSensor":
        capability = alexa_response.create_payload_endpoint_capability(
            interface=interface,
            supported=get_supportedproperty(interface),
            retrievable=True,
            proactively_reported=True)

    elif interface == "Alexa.ThermostatController":
        capability = alexa_response.create_payload_endpoint_capability(
            interface=interface,
            supported=get_supportedproperty(interface),
            configuration_modes=["HEAT", "COOL", "AUTO", "OFF"],
            retrievable=False,
            proactively_reported=True)

    elif interface == "Alexa.RangeController":
        capability = alexa_response.create_payload_endpoint_capability(
            interface=interface,
            instance=get_instance(interface),
            supported=get_supportedproperty(interface),
            retrievable=True,
            proactively_reported=True,
            capability_resources={"friendlyNames": [{"@type": "text", "value": {"text": "number", "locale": "en-US"}}]},
            configuration_range={"minimumValue": 0, "maximumValue": 100, "precision": 1})

    elif interface == "Alexa.ModeController":
        capability = alexa_response.create_payload_endpoint_capability(
            interface=interface,
            instance=get_instance(interface),
            supported=get_supportedproperty(interface),
            retrievable=True,
            proactively_reported=True,
            capability_resources={"friendlyNames": [
                {"@type": "asset", "value": {"assetId": "Alexa.Setting.Mode"}}]},
            configuration_modes=[
                {
                    "value": "Position.Up",
                    "modeResources": {
                        "friendlyNames": [
                            {
                                "@type": "asset",
                                "value": {
                                    "assetId": "Alexa.Value.Open"
                                }
                            },
                            {
                                "@type": "text",
                                "value": {
                                    "text": "Open",
                                    "locale": "en-US"
                                }
                            }
                        ]
                    }
                },
                {
                    "value": "Position.Down",
                    "modeResources": {
                        "friendlyNames": [
                            {
                                "@type": "asset",
                                "value": {
                                    "assetId": "Alexa.Value.Close"
                                }
                            },
                            {
                                "@type": "text",
                                "value": {
                                    "text": "Closed",
                                    "locale": "en-US"
                                }
                            }
                        ]
                    }
                }
            ],
            configuration_ordered=False,
            semantics_actions=[
                {
                    "@type": "ActionsToDirective",
                    "actions": ["Alexa.Actions.Close", "Alexa.Actions.Lower"],
                    "directive": {
                        "name": "SetMode",
                        "payload": {
                            "mode": "Position.Down"
                        }
                    }
                },
                {
                    "@type": "ActionsToDirective",
                    "actions": ["Alexa.Actions.Open", "Alexa.Actions.Raise"],
                    "directive": {
                        "name": "SetMode",
                        "payload": {
                            "mode": "Position.Up"
                        }
                    }
                }
            ],
            semantics_states=[
                {
                    "@type": "StatesToValue",
                    "states": ["Alexa.States.Closed"],
                    "value": "Position.Down"
                },
                {
                    "@type": "StatesToValue",
                    "states": ["Alexa.States.Open"],
                    "value": "Position.Up"
                }
            ])

    elif interface == "Alexa.EventDetectionSensor":
        capability = alexa_response.create_payload_endpoint_capability(
            interface=interface,
            supported=get_supportedproperty(interface),
            retrievable=False,
            proactively_reported=True)

    else:
        raise Exception(f"Capability not implemented yet for Interface: {interface}")

    return capability


def get_display(domain):
    if domain == "light":
        return "LIGHT"

    elif domain in ["script"]:
        return "ACTIVITY_TRIGGER"

    elif domain in ["climate"]:
        return "THERMOSTAT"

    else:
        return "OTHER"


async def discovery_handler(hass, request):
    # Prepare the Alexa response
    alexa_response = AlexaResponse(namespace="Alexa.Discovery",
                                   name="AddOrUpdateReport",
                                   payload={"scope": {"type": "BearerToken", "token": ""}})

    # Append alexa endpoint for each entity
    entities = hass.states.async_entity_ids()
    for entity_id in entities:
        _LOGGER.debug("Discovering entity: %s", entity_id)
        domain = entity_id.split(".")[0]

        state = hass.states.get(entity_id)

    # Append alexa endpoint for each entity
    entities = hass.states.async_entity_ids()
    for entity_id in entities:
        domain = entity_id.split(".")[0]
        state = hass.states.get(entity_id)

        capabilities = []
        for interface in get_interfaces(domain, state.attributes.get(ATTR_ALEXA_INTERFACE)):
            capabilities.append(get_capability(alexa_response, interface))
        
        if len(capabilities) > 0:
            alexa_response.add_payload_endpoint(
                endpoint_id=entity_id,
                friendly_name=state.attributes.get(ATTR_FRIENDLY_NAME),
                description=ATTR_DESCRIPTION,
                manufacturer_name=ATTR_MANUFACTURER,
                display_categories=[state.attributes.get(ATTR_ALEXA_DISPLAY, get_display(domain))],
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

    # Retrieve current HASS state
    state = hass.states.get(entity_id)

    if namespace == "Alexa.ModeController" and name == "SetMode":
        property_name = "mode"
        payload = {"entity_id": entity_id}
        property_value = request["directive"]["payload"]["mode"]
        if property_value == "Position.Up":
          service = "open_cover"
        else:
          service = "close_cover"

    if namespace == "Alexa.RangeController" and name == "AdjustRangeValue":
        property_name = "rangeValue"
        payload = {"entity_id": entity_id}
        property_value = request["directive"]["payload"]["rangeValueDelta"]
        if property_value > 0:
          service = "increment"
        else:
          service = "decrement"
        property_value = int(state.state) + int(property_value)

    if namespace == "Alexa.RangeController" and name == "SetRangeValue":
        property_name = "rangeValue"
        property_value = request["directive"]["payload"]["rangeValue"]
        service = "configure"
        payload = {"entity_id": entity_id, "value": property_value}

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
        domain = "climate"
        service = "set_temperature"
        property_value = request["directive"]["payload"]["targetSetpointDelta"]["value"]
        payload = {"entity_id": entity_id}
        payload["target_temp_high"] = state.attributes.get("target_temp_high") + property_value
        payload["target_temp_low"] = state.attributes.get("target_temp_low") + property_value
        property_name = "targetSetpoint"
        if property_value > 0:
            property_value = {"value": payload["target_temp_low"], "scale": "FAHRENHEIT"}
        else:
            property_value = {"value": payload["target_temp_high"], "scale": "FAHRENHEIT"}

    # Call HASS Service
    _LOGGER.debug("Hass Services Call, with domain: %s, service: %s and payload: %s", domain, service, payload)
    await hass.services.async_call(domain, service, payload)

    # Return an Alexa reponse
    alexa_response = AlexaResponse(correlation_token=correlation_token,
                                   scope_token=scope_token,
                                   endpoint_id=entity_id)
    alexa_response.add_context_property(namespace=namespace,
                                        name=property_name,
                                        value=property_value)
    return alexa_response.get()


def get_propertyvalue(interface, state):
    if interface in ["Alexa.EventDetectionSensor"]:
        property_value = {"value": "DETECTED"}

    elif interface in ["Alexa.ContactSensor", "Alexa.MotionSensor"]:
        if state.state.lower() == "open" or state.state.lower() == "on":
            property_value = "DETECTED"
        else:
            property_value = "NOT_DETECTED"

    elif interface in ["Alexa.TemperatureSensor"]:
        property_value = {"value": state.state, "scale": "FAHRENHEIT"}

    elif interface in ["Alexa.ModeController"]:
        if state.state.lower() == "open":
            property_value = "Position.Up"
        elif state.state.lower() == "closed":
            property_value = "Position.Down"
        else:
            property_value = "INVALID"

    elif interface in ["Alexa.RangeController"]:
        property_value = int(state.state)

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

    # TO-DO What to do with multiple inetrafces
    interface = get_interfaces(domain, state.attributes.get(ATTR_ALEXA_INTERFACE))[0]
    instance = get_instance(interface)

    alexa_response.add_context_property(
        namespace=interface,
        instance=instance,
        name=get_supportedproperty(interface)[0]["name"],
        value=get_propertyvalue(interface, state))

    return alexa_response.get()


async def change_handler(hass, entity_id):
    # Retrieve HASS state
    state = hass.states.get(entity_id)
    domain = entity_id.split(".")[0]

    # TO-DO What to do with multiple inetrafces
    interface = get_interfaces(domain, state.attributes.get(ATTR_ALEXA_INTERFACE))[0]
    instance = get_instance(interface)

    supported_property = get_supportedproperty(interface)
    if supported_property:
        alexa_response = AlexaResponse(namespace="Alexa",
                                       name="ChangeReport",
                                       endpoint_id=entity_id)
        alexa_response.add_payload_property(namespace=interface,
                                            instance=instance,
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
