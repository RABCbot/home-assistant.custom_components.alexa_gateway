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
    ATTR_DEVICE_CLASS, ATTR_FRIENDLY_NAME)
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


def get_interfaces(domain, attributes):
    interfaces = []
    device_class = attributes.get(ATTR_DEVICE_CLASS)
    override_interface = attributes.get(ATTR_ALEXA_INTERFACE)

    if not override_interface:
        if domain in ["lock"]:
            interfaces.append("Alexa.LockController")
            interfaces.append("Alexa")

        if domain in ["light"]:
            interfaces.append("Alexa.PowerController")
            interfaces.append("Alexa.BrightnessController")
            interfaces.append("Alexa.ColorController")
            interfaces.append("Alexa.ColorTemperatureController")
            interfaces.append("Alexa")

        elif domain in ["switch", "input_boolean"]:
            interfaces.append("Alexa.PowerController")
            interfaces.append("Alexa")

        elif domain in ["script"]:
            interfaces.append("Alexa.PowerController")
            interfaces.append("Alexa")

        elif domain in ["climate"]:
            interfaces.append("Alexa.TemperatureSensor")
            interfaces.append("Alexa.ThermostatController")
            interfaces.append("Alexa")

        elif domain in ["sensor", "binary_sensor"]:
            interfaces.append("Alexa.ContactSensor")
            interfaces.append("Alexa")

        elif domain in ["cover"] and device_class in ["garage", "door", "gate"]:
            interfaces.append("Alexa.ModeController")
            interfaces.append("Alexa")

        elif domain in ["cover"] and device_class in ["awning", "blind", "curtain", "shade", "shutter", "window"]:
            interfaces.append("Alexa.RangeController")
            interfaces.append("Alexa")

        elif domain in ["counter"]:
            interfaces.append("Alexa.RangeController")
            interfaces.append("Alexa")

    elif override_interface == "Alexa.DoorbellEventSource":
        interfaces.append("Alexa.DoorbellEventSource")

    elif override_interface != "None":
        interfaces.append(override_interface)
        interfaces.append("Alexa")

    return interfaces


def get_instance(interface, attributes):
    device_class = attributes.get(ATTR_DEVICE_CLASS)

    if device_class in ["garage", "door", "gate"]:
        return  "GarageDoor.Position"

    elif device_class in ["awning", "blind", "curtain", "shade", "shutter", "window"]:
        return "Blind.Lift"

    elif interface == "Alexa.RangeController":
        return "Counter.Number"

    else:
        return None

def get_asset_id(attributes):
    device_class = attributes.get(ATTR_DEVICE_CLASS)
    if device_class in ["garage", "door", "gate"]:
        return "Alexa.Setting.Mode"
        
    elif device_class in ["awning", "blind", "curtain", "shade", "shutter", "window"]:
        return "Alexa.Setting.Opening"

    else:
        return None


def get_capability(alexa_response, interface, attributes):
    device_class = attributes.get(ATTR_DEVICE_CLASS)
    
    if interface == "Alexa":
        capability = alexa_response.create_payload_endpoint_capability()

    elif interface == "Alexa.DoorbellEventSource":
        capability = alexa_response.create_payload_endpoint_capability(
            interface=interface,
            proactively_reported=True)

    elif interface in ["Alexa.LockController", "Alexa.BrightnessController", "Alexa.PowerController", "Alexa.TemperatureSensor", "Alexa.ColorController", "Alexa.ColorTemperatureController"]:
        capability = alexa_response.create_payload_endpoint_capability(
            interface=interface,
            supported=get_properties(interface),
            retrievable=True,
            proactively_reported=True)

    elif interface == "Alexa.ContactSensor":
        capability = alexa_response.create_payload_endpoint_capability(
            interface=interface,
            supported=get_properties(interface),
            retrievable=True,
            proactively_reported=True)

    elif interface == "Alexa.MotionSensor":
        capability = alexa_response.create_payload_endpoint_capability(
            interface=interface,
            supported=get_properties(interface),
            retrievable=True,
            proactively_reported=True)

    elif interface == "Alexa.ThermostatController":
        capability = alexa_response.create_payload_endpoint_capability(
            interface=interface,
            supported=get_properties(interface),
            configuration_modes=["HEAT", "COOL", "AUTO", "OFF"],
            retrievable=False,
            proactively_reported=True)

    elif interface == "Alexa.RangeController" and device_class in ["awning", "blind", "curtain", "shade", "shutter", "window"]:
        # TO-DO: Set "rangeValueDelta" from the state attributes step
        capability = alexa_response.create_payload_endpoint_capability(
            interface=interface,
            instance=get_instance(interface, attributes),
            supported=get_properties(interface),
            retrievable=True,
            proactively_reported=True,
            capability_resources={"friendlyNames": [
                {"@type": "asset", "value": {"assetId": get_asset_id(attributes)}}]},
            configuration_range={"minimumValue": 0, "maximumValue": 100, "precision": 1},
            unit_of_measure="Alexa.Unit.Percent",
            semantics_actions=[
                  {
                    "@type": "ActionsToDirective",
                    "actions": ["Alexa.Actions.Close"],
                    "directive": {
                      "name": "SetRangeValue",
                      "payload": {
                        "rangeValue": 0
                      }
                    }
                  },
                  {
                    "@type": "ActionsToDirective",
                    "actions": ["Alexa.Actions.Open"],
                    "directive": {
                      "name": "SetRangeValue",
                      "payload": {
                        "rangeValue": 100
                      }
                    }
                  },
                  {
                    "@type": "ActionsToDirective",
                    "actions": ["Alexa.Actions.Lower"],
                    "directive": {
                      "name": "AdjustRangeValue",
                      "payload": {
                        "rangeValueDelta" : -10,
                        "rangeValueDeltaDefault" : False
                      }
                    }
                  },
                  {
                    "@type": "ActionsToDirective",
                    "actions": ["Alexa.Actions.Raise"],
                    "directive": {
                      "name": "AdjustRangeValue",
                      "payload": {
                        "rangeValueDelta" : 10,
                        "rangeValueDeltaDefault" : False
                      }
                    }
                  }
                ],
            semantics_states=[
                  {
                    "@type": "StatesToValue",
                    "states": ["Alexa.States.Closed"],
                    "value": 0
                  },
                  {
                    "@type": "StatesToRange",
                    "states": ["Alexa.States.Open"],
                    "range": {
                      "minimumValue": 1,
                      "maximumValue": 100
                    }
                  }  
                ])

    elif interface == "Alexa.RangeController":
        capability = alexa_response.create_payload_endpoint_capability(
            interface=interface,
            instance=get_instance(interface, attributes),
            supported=get_properties(interface),
            retrievable=True,
            proactively_reported=True,
            capability_resources={"friendlyNames": [
                {"@type": "text", "value": {"text": "number", "locale": "en-US"}}]},
            configuration_range={"minimumValue": 0, "maximumValue": 100, "precision": 1})

    elif interface == "Alexa.ModeController" and device_class in ["garage", "door", "gate"]:
        capability = alexa_response.create_payload_endpoint_capability(
            interface=interface,
            instance=get_instance(interface, attributes),
            supported=get_properties(interface),
            retrievable=True,
            proactively_reported=True,
            capability_resources={"friendlyNames": [
                {"@type": "asset", "value": {"assetId": get_asset_id(attributes)}}]},
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
            supported=get_properties(interface),
            retrievable=False,
            proactively_reported=True)

    else:
        raise Exception(
            f"Capability not yet implemented for Interface: {interface}")

    return capability


def get_display(domain, attributes):
    device_class = attributes.get(ATTR_DEVICE_CLASS)

    if domain in ["light"]:
        return "LIGHT"

    elif domain in ["lock"]:
        return "SMARTLOCK"

    elif domain in ["script"]:
        return "ACTIVITY_TRIGGER"

    elif domain in ["climate"]:
        return "THERMOSTAT"

    elif domain in ["camera"]:
        return "CAMERA"

    elif device_class in ["garage"]:
        return "GARAGE_DOOR"

    elif device_class in ["door", "gate"]:
        return "DOOR"
        
    elif device_class in ["awning", "blind", "curtain", "shade", "shutter", "window"]:
        return "INTERIOR_BLIND"

    else:
        return "OTHER"


def get_properties(interface):
    if interface == "Alexa.ContactSensor":
        return [{"name": "detectionState"}]

    elif interface == "Alexa.MotionSensor":
        return [{"name": "detectionState"}]

    elif interface == "Alexa.TemperatureSensor":
        return [{"name": "temperature"}]

    elif interface == "Alexa.ThermostatController":
        return [{"name": "targetSetpoint"},
                {"name": "thermostatMode"},
                {"name": "lowerSetpoint"},
                {"name": "upperSetpoint"}]

    elif interface == "Alexa.PowerController":
        return [{"name": "powerState"}]

    elif interface == "Alexa.BrightnessController":
        return [{"name": "brightness"}]

    elif interface == "Alexa.ColorController":
        return [{"name": "color"}]

    elif interface == "Alexa.ColorTemperatureController":
        return [{"name": "colorTemperatureInKelvin"}]

    elif interface == "Alexa.EventDetectionSensor":
        return [{"name": "humanPresenceDetectionState"}]

    elif interface == "Alexa.DoorbellEventSource":
        return []

    elif interface == "Alexa.ModeController":
        return [{"name": "mode"}]

    elif interface == "Alexa.RangeController":
        return [{"name": "rangeValue"}]

    elif interface == "Alexa.LockController":
        return [{"name": "lockState"}]

    else:
        raise Exception(
            f"Supported Property not yet implemented for Interface: {interface}")


def get_propertyvalue(name, state):
    if name == "humanPresenceDetectionState":
        property_value = {"value": "DETECTED"}

    elif name == "detectionState":
        if state.state.lower() == "open" or state.state.lower() == "on":
            property_value = "DETECTED"
        else:
            property_value = "NOT_DETECTED"

    elif name == "temperature" and state.domain == "sensor":
        property_value = {"value": state.state, "scale": "FAHRENHEIT"}

    elif name == "temperature" and state.domain == "climate":
        property_value = {"value": state.attributes.get(
            "current_temperature"), "scale": "FAHRENHEIT"}

    elif name == "targetSetpoint" and state.domain == "climate":
        property_value = {"value": state.attributes.get(
            "current_temperature"), "scale": "FAHRENHEIT"}

    elif name == "lowerSetpoint" and state.domain == "climate":
        property_value = {"value": state.attributes.get(
            "target_temp_low"), "scale": "FAHRENHEIT"}

    elif name == "upperSetpoint" and state.domain == "climate":
        property_value = {"value": state.attributes.get(
            "target_temp_high"), "scale": "FAHRENHEIT"}

    elif name == "thermostatMode" and state.domain == "climate":
        property_value = state.state.upper()
        if property_value == "HEAT_COOL":
            property_value = "AUTO"

    elif name == "mode":
        if state.state.lower() == "open":
            property_value = "Position.Up"
        elif state.state.lower() == "closed":
            property_value = "Position.Down"
        else:
            property_value = "INVALID"

    elif name == "rangeValue" and state.domain == "cover":
        property_value = state.attributes.get("current_position")

    elif name == "rangeValue" and state.domain != "cover":
        property_value = int(state.state)

    elif name == "color":
        property_value = {
            "hue": 0.0,
            "saturation": 0.0,
            "brightness": 0.0
        }

    elif name == "colorTemperatureInKelvin":
        property_value = 0

    else:
        property_value = state.state.upper()

    return property_value


async def discovery_handler(hass, request):
    # Prepare the Alexa response
    alexa_response = AlexaResponse(namespace="Alexa.Discovery",
                                   name="AddOrUpdateReport",
                                   payload={"scope": {"type": "BearerToken", "token": ""}})

    # Append alexa endpoint for each entity
    entities = hass.states.async_entity_ids()
    for entity_id in entities:
        state = hass.states.get(entity_id)

        display_category = state.attributes.get(ATTR_ALEXA_DISPLAY, get_display(state.domain, state.attributes))
        capabilities = []
        for interface in get_interfaces(state.domain, state.attributes):
            capabilities.append(get_capability(alexa_response, interface, state.attributes))

        if len(capabilities) > 0:
            alexa_response.add_payload_endpoint(
                endpoint_id=entity_id,
                friendly_name=state.attributes.get(ATTR_FRIENDLY_NAME),
                description=ATTR_DESCRIPTION,
                manufacturer_name=ATTR_MANUFACTURER,
                display_categories=[display_category],
                capabilities=capabilities)

    return alexa_response.get()


def get_service(interface, name, payload, state):

    if interface == "Alexa.ModeController" and name == "SetMode":
        if payload["mode"] == "Position.Up":
            service = "open_cover"
        else:
            service = "close_cover"
        data = {"entity_id": state.entity_id}

    elif interface == "Alexa.RangeController" and name == "AdjustRangeValue" and state.domain == "cover":
        service = "set_cover_position"
        data = {"entity_id": state.entity_id, "position": state.attributes.get("current_position") + payload["rangeValueDelta"]}

    elif interface == "Alexa.RangeController" and name == "SetRangeValue" and state.domain == "cover":
        service = "set_cover_position"
        data = {"entity_id": state.entity_id, "position": payload["rangeValue"]}

    elif interface == "Alexa.RangeController" and name == "AdjustRangeValue":
        if payload["rangeValueDelta"] > 0:
            service = "increment"
        else:
            service = "decrement"
        data = {"entity_id": state.entity_id}

    elif interface == "Alexa.RangeController" and name == "SetRangeValue":
        service = "configure"
        data = {"entity_id": state.entity_id, "value": payload["rangeValue"]}

    elif interface == "Alexa.LockController":
        service = name.lower()
        data = {"entity_id": state.entity_id}

    elif interface == "Alexa.PowerController":
        if name == "TurnOff":
            service = "turn_off"
        else:
            service = "turn_on"
        data = {"entity_id": state.entity_id}

    elif interface == "Alexa.BrightnessController":
        service = "turn_on"
        data = {"entity_id": state.entity_id,
                "brightness_pct": payload["brightness"]}

    elif interface == "Alexa.ColorController" and name == "SetColor":
        service = "turn_on"
        data = {"entity_id": state.entity_id,
                "hs_color": [payload["color"]["hue"], 100 * payload["color"]["saturation"]]}

    elif interface == "Alexa.ColorTemperatureController" and name == "SetColorTemperature":
        service = "turn_on"
        data = {"entity_id": state.entity_id,
                "kelvin": payload["colorTemperatureInKelvin"]}

    elif interface == "Alexa.ThermostatController" and name == "AdjustTargetTemperature":
        service = "set_temperature"
        data = {"entity_id": state.entity_id}
        data["target_temp_high"] = state.attributes.get(
            "target_temp_high") + payload["targetSetpointDelta"]["value"]
        data["target_temp_low"] = state.attributes.get(
            "target_temp_low") + payload["targetSetpointDelta"]["value"]

    elif interface == "Alexa.ThermostatController" and name == "SetTargetTemperature":
        service = "set_temperature"
        data = {"entity_id": state.entity_id}
        if "upperSetpoint" in payload: data["target_temp_high"] = payload["upperSetpoint"]["value"]
        if "lowerSetpoint" in payload: data["target_temp_low"] = payload["lowerSetpoint"]["value"]
        if "targetSetpoint" in payload: 
            data["target_temp_high"] = payload["targetSetpoint"]["value"] + 4
            data["target_temp_low"] = payload["targetSetpoint"]["value"] - 4

    else:
        raise Exception(
            f"Service not yet implemented for Interface: {interface}; name: {name}")

    return service, data


def get_futurevalue(name, service, data, state):

    if service == "open_cover":
        return "Position.Up"

    elif service == "close_cover":
        return "Position.Down"

    elif service == "increment":
        return int(state.state) + 1

    elif service == "decrement":
        return int(state.state) - 1

    elif service == "configure":
        return data["value"]

    elif service == "set_cover_position":
        return data["position"]

    elif service == "turn_off":
        return "OFF"

    elif service == "turn_on":
        return "ON"

    elif service == "lock":
        return "LOCKED"

    elif service == "unlock":
        return "UNLOCKED"

    elif "brightness_pct" in data:
        return data["brightness_pct"]

    elif name == "thermostatMode":
        return {"value": state.state}

    elif name == "lowerSetpoint":
        return {"value": data["target_temp_low"], "scale": "FAHRENHEIT"}

    elif name == "upperSetpoint":
        return {"value": data["target_temp_high"], "scale": "FAHRENHEIT"}

    elif name == "targetSetpoint":
        return {"value": state.attributes.get("current_temperature"), "scale": "FAHRENHEIT"}
        
    else:
        raise Exception(
            f"Future value not yet implemented for name: {name}; service: {service}")



async def service_handler(hass, request):
    # Extract Alexa request values and map to Home-Assistant
    name = request["directive"]["header"]["name"]
    interface = request["directive"]["header"]["namespace"]
    correlation_token = request["directive"]["header"]["correlationToken"]
    scope_token = request["directive"]["endpoint"]["scope"]["token"]
    entity_id = request["directive"]["endpoint"]["endpointId"]
    payload = request["directive"]["payload"]

    # Retrieve current HASS state
    state = hass.states.get(entity_id)

    # Call HASS Service
    service, data = get_service(interface, name, payload, state)
    _LOGGER.debug(
        "Hass Services Call, with domain: %s, service: %s and payload: %s", state.domain, service, data)
    await hass.services.async_call(state.domain, service, data)

    # Return an Alexa reponse
    alexa_response = AlexaResponse(correlation_token=correlation_token,
                                   scope_token=scope_token,
                                   endpoint_id=entity_id)

    instance = get_instance(interface, state.attributes)

    # TO-DO: Dont use future value
    for prop in get_properties(interface):
        alexa_response.add_context_property(
            namespace=interface,
            instance=instance,
            name=prop["name"],
            value=get_futurevalue(prop["name"], service, data, state))

    return alexa_response.get()


async def report_handler(hass, request):
    # Extract Alexa request values and map to Home-Assistant
    correlation_token = request["directive"]["header"]["correlationToken"]
    scope_token = request["directive"]["endpoint"]["scope"]["token"]
    entity_id = request["directive"]["endpoint"]["endpointId"]

    # Prepare Alexa reponse
    alexa_response = AlexaResponse(name="StateReport",
                                   correlation_token=correlation_token,
                                   scope_token=scope_token,
                                   endpoint_id=entity_id)

    # Retrieve HASS state
    state = hass.states.get(entity_id)

    interfaces = get_interfaces(state.domain, state.attributes)
    if "Alexa" in interfaces: interfaces.remove("Alexa")
    for interface in interfaces:
        instance = get_instance(interface, state.attributes)

        for prop in get_properties(interface):
            alexa_response.add_context_property(
                namespace=interface,
                instance=instance,
                name=prop["name"],
                value=get_propertyvalue(prop["name"], state))

    return alexa_response.get()


async def change_handler(hass, entity_id):
    # Retrieve HASS state
    state = hass.states.get(entity_id)

    interfaces = get_interfaces(state.domain, state.attributes)
    if "Alexa" in interfaces: interfaces.remove("Alexa")
    for interface in interfaces:
        instance = get_instance(interface, state.attributes)

        props = get_properties(interface)
        if len(props) > 0:
            alexa_response = AlexaResponse(namespace="Alexa",
                                           name="ChangeReport",
                                           endpoint_id=entity_id)
            for prop in props:
                alexa_response.add_payload_property(namespace=interface,
                                                    instance=instance,
                                                    name=prop["name"],
                                                    value=get_propertyvalue(prop["name"], state))

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
