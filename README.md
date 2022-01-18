# custom_components/alexa_gateway
This is a Home-Assistant custom component to be used together with an Alexa SmartHome skill

## Why?
Why not?, learning main reason

## Setup
Alexa SmartHome Skill</br>
Alexa Account Linking</br>
AWS Lambda</br>
AWS IoT GreenGrass core</br>
This custom component</br>

## Services
The custom component register two services:</br>
### process_request
To be called from your lambda running the local Greengrass IoT core
### report_Change
To be called from an Automation in Home-assistant to send your entity status change to the Alexa Event Gateway
reference: https://developer.amazon.com/en-US/docs/alexa/smarthome/send-events-to-the-alexa-event-gateway.html

## Account Linking
reference:  https://developer.amazon.com/blogs/post/Tx3CX1ETRZZ2NPC/Alexa-Account-Linking-5-Steps-to-Seamlessly-Link-Your-Alexa-Skill-with-Login-wit

## Configuration
```
alexa_gateway:
  url: https://api.amazonalexa.com/v3/events
  auth_url: https://api.amazon.com/auth/o2/token
  client_id: !secret ALEXA_CLIENT_ID
  client_secret: !secret  ALEXA_CLIENT_SECRET
```

## Customize
It is possible to override the Alexa interface and Alexa display values</br>
For example, for an entity you can make it as a Doorbell event
```
script.doorbell:
  alexa_interface: Alexa.DoorbellEventSource
  alexa_display: DOORBELL
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
Alexa.ModeController (garage door)</br>
Alexa.RangeController (generic counter and blinds)</br>
Alexa.EventDetectionSensor</br>
Alexa.DoorbellEventSource</br>

reference: https://developer.amazon.com/en-US/docs/alexa/device-apis/list-of-interfaces.html

## License
alexa_response.py
Copyright 2018 Amazon.com, Inc. or its affiliates. All Rights Reserved
