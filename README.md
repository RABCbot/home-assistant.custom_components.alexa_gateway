# Alexa Gateway
This is a Home-Assistant custom component to be used together with an Alexa SmartHome skill

## Why?
Why not?, learning main reason

## Setup
Alexa SmartHome Skill
AWS Lambda
AWS IoT GreenGrass core
This custom component

## Configuration
```
alexa_gateway:
  url: https://api.amazonalexa.com/v3/events
  auth_url: https://api.amazon.com/auth/o2/token
  client_id: !secret ALEXA_CLIENT_ID
  client_secret: !secret  ALEXA_CLIENT_SECRET
```
