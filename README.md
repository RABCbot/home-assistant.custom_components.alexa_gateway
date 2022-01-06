# Alexa Gateway
This is a Home-Assistant custom component to be used together with an Alexa SmartHome skill

## Why?
Why not?, learning main reason

## Setup
Alexa SmartHome Skill</br>
AWS Lambda</br>
AWS IoT GreenGrass core</br>
This custom component</br>

## Configuration
```
alexa_gateway:
  url: https://api.amazonalexa.com/v3/events
  auth_url: https://api.amazon.com/auth/o2/token
  client_id: !secret ALEXA_CLIENT_ID
  client_secret: !secret  ALEXA_CLIENT_SECRET
```

## Customize
It is possible to overrides the Alexa interface and Alexa display values
For example, for an entity that controls your garage door, add these attributes in the customize 
```
alexa_interface: Alexa.ModeController
alexa_display: GARAGE_DOOR
```

## Supported Alexa interfaces
Alexa.ContactSensor</br>
Alexa.MotionSensor</br>
Alexa.TemperatureSensor</br>
Alexa.ThermostatController</br>
Alexa.PowerController</br>
Alexa.BrightnessController</br>
Alexa.ColorController</br>
Alexa.ColorTemperatureController</br>
Alexa.ModeController</br>
Alexa.RangeController</br>
Alexa.EventDetectionSensor</br>
Alexa.DoorbellEventSource</br>

reference: https://developer.amazon.com/en-US/docs/alexa/device-apis/list-of-interfaces.html

## License
alexa_response.py
Copyright 2018 Amazon.com, Inc. or its affiliates. All Rights Reserved
