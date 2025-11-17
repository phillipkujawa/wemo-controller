# Deployment Guide - WeMo + Govee Controller

## Architecture

The event-driven system consists of:
- **Backend API**: FastAPI with MQTT and SSE support
- **Frontend**: Static HTML/JS with EventSource for real-time updates
- **Event System**: MQTT for Govee events → SSE for browser updates

## Deployment Options

### Option 1: Cloudflare Pages + External Backend (Recommended)

Since Cloudflare Workers don't support long-running WebSocket/MQTT connections well, use:

**Frontend on Cloudflare Pages:**
1. Deploy static `index.html` to Cloudflare Pages
2. Update `API_BASE` in `index.html` to point to your backend URL

**Backend on Cloud Provider with WebSocket support:**
- Railway.app
- Fly.io
- Render.com
- DigitalOcean App Platform
- AWS/GCP/Azure

#### Deploy Backend to Railway.app

1. Install Railway CLI:
```bash
npm install -g @railway/cli
```

2. Login and initialize:
```bash
railway login
railway init
```

3. Create `railway.json`:
```json
{
  "$schema": "https://railway.app/railway.schema.json",
  "build": {
    "builder": "NIXPACKS"
  },
  "deploy": {
    "startCommand": "uvicorn main:app --host 0.0.0.0 --port $PORT",
    "restartPolicyType": "ON_FAILURE",
    "restartPolicyMaxRetries": 10
  }
}
```

4. Add environment variables:
```bash
railway variables set GOVEE_API_KEY=your-api-key-here
railway variables set PORT=8000
```

5. Deploy:
```bash
railway up
```

#### Deploy Frontend to Cloudflare Pages

1. Install Wrangler:
```bash
npm install -g wrangler
```

2. Login to Cloudflare:
```bash
wrangler login
```

3. Update `index.html` - change API_BASE to your Railway backend URL:
```javascript
const API_BASE = "https://your-app.railway.app";
```

4. Deploy to Cloudflare Pages:
```bash
wrangler pages deploy . --project-name=wemo-govee-controller
```

### Option 2: Fly.io (Backend + Frontend)

Fly.io supports WebSockets and long-running connections.

1. Install flyctl:
```bash
curl -L https://fly.io/install.sh | sh
```

2. Login:
```bash
fly auth login
```

3. Create `fly.toml`:
```toml
app = "wemo-govee-controller"

[build]
  builder = "paketobuildpacks/builder:base"

[env]
  PORT = "8000"

[[services]]
  internal_port = 8000
  protocol = "tcp"

  [[services.ports]]
    handlers = ["http"]
    port = 80

  [[services.ports]]
    handlers = ["tls", "http"]
    port = 443

  [services.concurrency]
    hard_limit = 25
    soft_limit = 20

[[services.http_checks]]
  interval = 10000
  timeout = 2000
  grace_period = "5s"
  method = "get"
  path = "/devices"
```

4. Create `Procfile`:
```
web: uvicorn main:app --host 0.0.0.0 --port $PORT
```

5. Set secrets:
```bash
fly secrets set GOVEE_API_KEY=your-api-key-here
```

6. Deploy:
```bash
fly deploy
```

7. Update `index.html` API_BASE to your Fly.io URL

### Option 3: Render.com (Simplest)

1. Push code to GitHub

2. Go to https://render.com

3. Create New Web Service

4. Connect your GitHub repo

5. Configure:
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `uvicorn main:app --host 0.0.0.0 --port $PORT`
   - **Environment Variables**: Add `GOVEE_API_KEY`

6. Deploy

7. Update `index.html` API_BASE to your Render URL

## Local Development

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Set environment variable:
```bash
export GOVEE_API_KEY=your-api-key-here
```

3. Run the server:
```bash
uvicorn main:app --reload --port 8002
```

4. Open `index.html` in browser or serve it:
```bash
python -m http.server 8080
```

## Features

### Real-time Event System
- **MQTT Connection**: Subscribes to Govee device events
- **Server-Sent Events (SSE)**: Pushes updates to browser in real-time
- **Automatic Reconnection**: Frontend auto-reconnects if connection drops

### Event Types
- `wemo_state_change`: WeMo device turned on/off/toggle
- `govee_state_change`: Govee device state changed
- `govee_event`: Govee device sensor events (water low, presence detected, etc.)

### API Endpoints
- `GET /events` - SSE stream for real-time updates
- `POST /discover` - Discover WeMo devices
- `GET /devices` - List WeMo devices
- `POST /devices/{id}/{action}` - Control WeMo device
- `POST /govee/discover` - Discover Govee devices
- `GET /govee/devices` - List Govee devices
- `POST /govee/devices/{id}/{action}` - Control Govee device

## Security Notes

1. **API Key Protection**: Never commit `GOVEE_API_KEY` to git
2. **CORS**: Update CORS settings in production for security
3. **HTTPS**: Use HTTPS in production (all cloud providers support this)
4. **Rate Limiting**: Consider adding rate limiting for production use

## Monitoring

- Check backend logs for MQTT connection status
- Monitor SSE connections in browser DevTools → Network tab
- Look for "MQTT: Connected successfully" in backend logs
