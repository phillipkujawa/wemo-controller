# WeMo + Govee Smart Home Controller

Event-driven, reactive smart home controller with real-time updates via Server-Sent Events and MQTT.

## Features

- 🔄 **Real-time Updates**: Instant device state changes pushed to browser via SSE
- 📡 **MQTT Integration**: Subscribe to Govee device events (water low, presence detected, etc.)
- 🎮 **WeMo Control**: Discover and control WeMo smart plugs on your local network
- 🌈 **Govee Integration**: Full cloud API integration with Govee smart devices
- 🔌 **Event-Driven Architecture**: Reactive frontend that updates automatically
- 🚀 **Production Ready**: Deploy to Railway, Render, Fly.io, or Vercel

## Quick Deploy

### Deploy Backend (Choose One):

[![Deploy on Railway](https://railway.app/button.svg)](https://railway.app/new/template?template=https://github.com/phillipkujawa/wemo-controller)

**OR**

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/phillipkujawa/wemo-controller)

**After deployment:**
1. Add environment variable: `GOVEE_API_KEY=7c91d5cc-26c7-42fc-a10f-b177eba5c715`
2. Copy your deployed URL
3. Update `index.html` line 292 with your backend URL
4. Open `index.html` in your browser

## Manual Deployment

See [DEPLOY_NOW.md](DEPLOY_NOW.md) for detailed step-by-step instructions for:
- Railway.app (CLI)
- Render.com (Dashboard)
- Fly.io
- Vercel

## Local Development

1. **Install dependencies:**
```bash
pip install -r requirements.txt
```

2. **Set environment variable:**
```bash
export GOVEE_API_KEY=your-api-key-here
```

3. **Run backend:**
```bash
uvicorn main:app --reload --port 8002
```

4. **Open frontend:**
```bash
open index.html
# Or serve it:
python -m http.server 8080
```

## Architecture

```
┌─────────────┐
│   Browser   │
│  (index.html)│
└──────┬──────┘
       │ EventSource (SSE)
       │ HTTP API calls
       │
┌──────▼──────────────┐
│   FastAPI Backend   │
│   (main.py)         │
│                     │
│  ┌───────────────┐  │
│  │  SSE Broadcaster│ │
│  └───────┬───────┘  │
│          │          │
│  ┌───────▼───────┐  │
│  │  MQTT Client  │  │
│  └───────┬───────┘  │
└──────────┼──────────┘
           │
    ┌──────▼──────┐
    │ Govee MQTT  │
    │   Broker    │
    └─────────────┘
```

## API Endpoints

### Real-time Events
- `GET /events` - Server-Sent Events stream for live updates

### WeMo Devices
- `POST /discover` - Discover WeMo devices on LAN
- `GET /devices` - List known WeMo devices
- `POST /devices/{id}/on` - Turn device on
- `POST /devices/{id}/off` - Turn device off
- `POST /devices/{id}/toggle` - Toggle device state

### Govee Devices
- `POST /govee/discover` - Discover Govee devices from cloud
- `GET /govee/devices` - List Govee devices
- `POST /govee/devices/{id}/on` - Turn device on
- `POST /govee/devices/{id}/off` - Turn device off

## Event Types

The SSE endpoint pushes these event types:

- **`connected`**: Initial connection established
- **`wemo_state_change`**: WeMo device state changed
- **`govee_state_change`**: Govee device state changed
- **`govee_event`**: Govee sensor event (water low, presence detected, etc.)
- **`keepalive`**: Periodic heartbeat

## Technologies

- **Backend**: FastAPI, Python 3.9+
- **Real-time**: Server-Sent Events (SSE), MQTT
- **Frontend**: Vanilla JavaScript, EventSource API
- **Device APIs**: pywemo, Govee OpenAPI v2

## Configuration

### Environment Variables

- `GOVEE_API_KEY` (required) - Your Govee API key from https://developer.govee.com
- `PORT` (optional) - Server port (default: 8000)

### MQTT Connection

The backend automatically connects to Govee's MQTT broker:
- Host: `mqtt.openapi.govee.com:8883`
- Protocol: MQTT over TLS
- Topic: `GA/{YOUR_API_KEY}`

## Requirements

See [requirements.txt](requirements.txt):
- fastapi
- uvicorn[standard]
- pywemo
- requests
- pydantic
- paho-mqtt
- sse-starlette

## License

MIT

## Credits

Built with [Claude Code](https://claude.com/claude-code)
