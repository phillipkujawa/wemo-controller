from typing import Dict, List, Optional, Any
import threading
import logging
import os
import uuid
import json
import asyncio
from queue import Queue

import requests
import pywemo
import paho.mqtt.client as mqtt
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

# -----------------------------
# Logging
# -----------------------------
logger = logging.getLogger("wemo")
logging.basicConfig(level=logging.INFO)

# -----------------------------
# Govee config (Awesome New API)
# -----------------------------
GOVEE_API_KEY = "7c91d5cc-26c7-42fc-a10f-b177eba5c715"
GOVEE_API_BASE = "https://openapi.api.govee.com"

# -----------------------------
# WeMo state
# -----------------------------
device_lock = threading.Lock()
devices: Dict[str, Any] = {}  # key = serialnumber or name

# -----------------------------
# Govee state
# -----------------------------
govee_lock = threading.Lock()
# key format: "<sku>|<device>"
govee_devices: Dict[str, dict] = {}

# -----------------------------
# Event Broadcasting
# -----------------------------
event_queues: List[Queue] = []
event_queues_lock = threading.Lock()

# -----------------------------
# MQTT Client for Govee Events
# -----------------------------
mqtt_client: Optional[mqtt.Client] = None
mqtt_connected = False


# -----------------------------
# FastAPI app
# -----------------------------
app = FastAPI(title="WeMo + Govee Controller API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],      # OK for local dev; lock down in prod
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# -----------------------------
# Models
# -----------------------------
class DeviceInfo(BaseModel):
    # WeMo
    id: str
    name: str
    model: Optional[str] = None
    host: Optional[str] = None
    port: Optional[int] = None
    state: Optional[int] = None
    insight_params: Optional[Dict[str, Any]] = None


class RenameRequest(BaseModel):
    name: str


class GoveeDeviceInfo(BaseModel):
    id: str                 # "<sku>|<device>"
    name: Optional[str] = None
    model: str              # sku
    device: str             # device id from Govee
    controllable: bool = True
    retrievable: bool = True
    state: Optional[str] = None   # "on"/"off"/"unknown"
    online: Optional[bool] = None


# -----------------------------
# Event Broadcasting Functions
# -----------------------------
def broadcast_event(event_type: str, data: dict):
    """Broadcast an event to all connected SSE clients."""
    event = {
        "type": event_type,
        "data": data,
        "timestamp": str(uuid.uuid4())
    }

    with event_queues_lock:
        for q in event_queues:
            try:
                q.put_nowait(event)
            except:
                pass


# -----------------------------
# MQTT Functions
# -----------------------------
def on_mqtt_connect(client, userdata, flags, rc):
    """Callback when MQTT connects."""
    global mqtt_connected
    if rc == 0:
        logger.info("MQTT: Connected successfully")
        mqtt_connected = True
        topic = f"GA/{GOVEE_API_KEY}"
        client.subscribe(topic)
        logger.info(f"MQTT: Subscribed to topic {topic}")
    else:
        logger.error(f"MQTT: Connection failed with code {rc}")
        mqtt_connected = False


def on_mqtt_disconnect(client, userdata, rc):
    """Callback when MQTT disconnects."""
    global mqtt_connected
    mqtt_connected = False
    logger.warning(f"MQTT: Disconnected with code {rc}")


def on_mqtt_message(client, userdata, msg):
    """Callback when MQTT message received."""
    try:
        payload = json.loads(msg.payload.decode())
        logger.info(f"MQTT: Received event: {payload}")

        # Extract device info
        sku = payload.get("sku")
        device_id = payload.get("device")
        device_name = payload.get("deviceName", "Unknown")

        if sku and device_id:
            device_key = f"{sku}|{device_id}"

            # Update local state
            capabilities = payload.get("capabilities", [])
            for cap in capabilities:
                if cap.get("type") == "devices.capabilities.event":
                    instance = cap.get("instance")
                    state = cap.get("state", [])

                    # Broadcast event to all connected clients
                    broadcast_event("govee_event", {
                        "deviceId": device_key,
                        "deviceName": device_name,
                        "sku": sku,
                        "device": device_id,
                        "eventType": instance,
                        "state": state
                    })

    except Exception as e:
        logger.error(f"MQTT: Error processing message: {e}")


def init_mqtt():
    """Initialize MQTT connection to Govee."""
    global mqtt_client

    if not GOVEE_API_KEY:
        logger.warning("MQTT: No GOVEE_API_KEY, skipping MQTT initialization")
        return

    try:
        mqtt_client = mqtt.Client(client_id=f"wemo-controller-{uuid.uuid4()}")
        mqtt_client.username_pw_set(GOVEE_API_KEY, GOVEE_API_KEY)
        mqtt_client.on_connect = on_mqtt_connect
        mqtt_client.on_disconnect = on_mqtt_disconnect
        mqtt_client.on_message = on_mqtt_message

        mqtt_client.tls_set()
        mqtt_client.connect_async("mqtt.openapi.govee.com", 8883, 60)
        mqtt_client.loop_start()

        logger.info("MQTT: Connection initiated")
    except Exception as e:
        logger.error(f"MQTT: Failed to initialize: {e}")


# -----------------------------
# WeMo helpers
# -----------------------------
def _store_wemo_devices(found: List[Any]) -> List[Any]:
    """Put discovered WeMo devices in the global dict."""
    with device_lock:
        for d in found:
            serial = getattr(d, "serialnumber", None) or d.name
            logger.info(
                "WeMo discovered: name=%s serial=%s host=%s port=%s",
                getattr(d, "name", "?"),
                serial,
                getattr(d, "host", "?"),
                getattr(d, "port", "?"),
            )
            devices[serial] = d
    return list(devices.values())


def discover_wemo_devices() -> List[Any]:
    """
    Discover WeMo devices on the local network using pywemo.
    """
    logger.info("WeMo: starting discovery…")
    found = pywemo.discover_devices()
    logger.info("WeMo: discover_devices() returned %d device(s)", len(found))
    return _store_wemo_devices(found)


def get_wemo_device_or_404(device_id: str) -> Any:
    with device_lock:
        device = devices.get(device_id)
    if device is None:
        raise HTTPException(status_code=404, detail=f"WeMo device '{device_id}' not found")
    return device


def wemo_device_to_info(device: Any) -> DeviceInfo:
    serial = getattr(device, "serialnumber", None) or device.name
    model_name = getattr(device, "model_name", device.__class__.__name__)
    host = getattr(device, "host", None)
    port = getattr(device, "port", None)

    try:
        state = device.get_state()
    except Exception as e:
        logger.warning("WeMo: error getting state for %s: %s", serial, e)
        state = None

    insight_params: Optional[Dict[str, Any]] = None
    try:
        if hasattr(device, "update_insight_params"):
            device.update_insight_params()
        if hasattr(device, "insight_params"):
            insight_params = dict(device.insight_params)
    except Exception as e:
        logger.warning("WeMo: error getting insight_params for %s: %s", serial, e)
        insight_params = None

    return DeviceInfo(
        id=serial,
        name=device.name,
        model=model_name,
        host=host,
        port=port,
        state=state,
        insight_params=insight_params,
    )


# -----------------------------
# Govee helpers (Awesome New API)
# -----------------------------
def govee_request(path: str, method: str = "GET", **kwargs) -> requests.Response:
    """
    Low-level wrapper around the Govee Platform API.
    Uses the 'Awesome New API' endpoints under /router/api/v1.
    """
    if not GOVEE_API_KEY:
        raise RuntimeError("GOVEE_API_KEY environment variable is not set")

    headers = kwargs.pop("headers", {})
    headers.setdefault("Govee-API-Key", GOVEE_API_KEY)
    headers.setdefault("Content-Type", "application/json")

    url = f"{GOVEE_API_BASE}{path}"
    resp = requests.request(method, url, headers=headers, timeout=10, **kwargs)
    if not resp.ok:
        logger.error("Govee API error %s: %s", resp.status_code, resp.text)
        raise HTTPException(
            status_code=502,
            detail=f"Govee API error {resp.status_code}: {resp.text}",
        )
    return resp


def govee_discover_devices() -> List[dict]:
    """
    GET /router/api/v1/user/devices

    Returns list of:
      { "sku": "...", "device": "...", "capabilities": [...] }
    """
    logger.info("Govee: discovering devices via /user/devices")
    resp = govee_request("/router/api/v1/user/devices", method="GET")
    payload = resp.json()

    if payload.get("code") != 200:
        raise HTTPException(status_code=502, detail=f"Govee list devices failed: {payload}")

    data = payload.get("data", [])
    with govee_lock:
        govee_devices.clear()
        for d in data:
            sku = d["sku"]
            dev = d["device"]
            key = f"{sku}|{dev}"
            govee_devices[key] = d

    return list(govee_devices.values())


def _govee_state_from_payload(sku: str, dev: str, state_payload: dict) -> GoveeDeviceInfo:
    """
    Convert Device State payload → our GoveeDeviceInfo.
    POST /router/api/v1/device/state returns:
      { code, msg, payload: { sku, device, capabilities: [...] } }
    """
    caps = state_payload.get("capabilities", [])
    online = None
    power_state = "unknown"

    for c in caps:
        c_type = c.get("type")
        instance = c.get("instance")
        state = c.get("state", {}) or {}
        value = state.get("value")

        if c_type == "devices.capabilities.online":
            online = bool(value)
        if c_type == "devices.capabilities.on_off" and instance == "powerSwitch":
            # Govee docs: value 1=on, 0=off
            if value == 1:
                power_state = "on"
            elif value == 0:
                power_state = "off"

    name = state_payload.get("deviceName")

    return GoveeDeviceInfo(
        id=f"{sku}|{dev}",
        name=name,
        model=sku,
        device=dev,
        state=power_state,
        online=online,
    )


def govee_get_state(device_id: str) -> GoveeDeviceInfo:
    """
    POST /router/api/v1/device/state
    Body:
      { "requestId": "uuid", "payload": { "sku": "...", "device": "..." } }
    """
    with govee_lock:
        raw = govee_devices.get(device_id)
    if not raw:
        raise HTTPException(status_code=404, detail="Govee device not found")

    sku, dev = device_id.split("|", 1)

    body = {
        "requestId": str(uuid.uuid4()),
        "payload": {"sku": sku, "device": dev},
    }

    resp = govee_request("/router/api/v1/device/state", method="POST", json=body)
    payload = resp.json()
    if payload.get("code") != 200:
        raise HTTPException(status_code=502, detail=f"Govee state failed: {payload}")

    state_payload = payload.get("payload", {})
    return _govee_state_from_payload(sku, dev, state_payload)


def govee_control(device_id: str, action: str) -> GoveeDeviceInfo:
    """
    POST /router/api/v1/device/control

    For simple on/off we send a single capability:
      type:     devices.capabilities.on_off
      instance: powerSwitch
      value:    1 (on) / 0 (off)
    """
    action = action.lower()
    if action not in {"on", "off"}:
        raise HTTPException(status_code=400, detail="Unsupported Govee action; use 'on' or 'off'")

    with govee_lock:
        raw = govee_devices.get(device_id)
    if not raw:
        raise HTTPException(status_code=404, detail="Govee device not found")

    sku, dev = device_id.split("|", 1)
    value = 1 if action == "on" else 0

    body = {
        "requestId": str(uuid.uuid4()),
        "payload": {
            "sku": sku,
            "device": dev,
            "capability": {
                "type": "devices.capabilities.on_off",
                "instance": "powerSwitch",
                "value": value,
            },
        },
    }

    logger.info("Govee: control %s (%s) → %s", sku, dev, action)
    govee_request("/router/api/v1/device/control", method="POST", json=body)
    # Then re-read state so frontend sees updated status
    return govee_get_state(device_id)


# -----------------------------
# Lifecycle
# -----------------------------
@app.on_event("startup")
def startup_discover():
    """Optional: discover WeMo once at startup so /devices isn't empty."""
    try:
        discover_wemo_devices()
    except Exception as e:
        logger.warning("WeMo startup discovery failed: %s", e)

    # Initialize MQTT for Govee events
    init_mqtt()


@app.on_event("shutdown")
def shutdown_mqtt():
    """Clean up MQTT connection on shutdown."""
    global mqtt_client
    if mqtt_client:
        mqtt_client.loop_stop()
        mqtt_client.disconnect()
        logger.info("MQTT: Disconnected")


# -----------------------------
# Server-Sent Events (SSE) Route
# -----------------------------
@app.get("/events")
async def events(request: Request):
    """
    Server-Sent Events endpoint for real-time updates.
    Clients connect here to receive live device state changes.
    """
    async def event_generator():
        q = Queue()
        with event_queues_lock:
            event_queues.append(q)

        try:
            # Send initial connection message
            yield {
                "event": "connected",
                "data": json.dumps({"message": "Connected to event stream"})
            }

            while True:
                # Check if client disconnected
                if await request.is_disconnected():
                    break

                # Check for new events (non-blocking)
                try:
                    event = q.get_nowait()
                    yield {
                        "event": event["type"],
                        "data": json.dumps(event["data"])
                    }
                except:
                    # No events, send keepalive
                    await asyncio.sleep(1)
                    yield {
                        "event": "keepalive",
                        "data": json.dumps({"timestamp": str(uuid.uuid4())})
                    }

        finally:
            # Clean up when client disconnects
            with event_queues_lock:
                if q in event_queues:
                    event_queues.remove(q)

    return EventSourceResponse(event_generator())


# -----------------------------
# WeMo routes
# -----------------------------
@app.post("/discover", response_model=List[DeviceInfo])
def api_discover_wemo():
    """
    Trigger a network discovery and return the full updated WeMo device list.
    """
    try:
        found = discover_wemo_devices()
    except Exception as e:
        logger.exception("Error during WeMo discovery")
        raise HTTPException(status_code=500, detail=f"WeMo discovery failed: {e}")
    return [wemo_device_to_info(d) for d in found]


@app.get("/devices", response_model=List[DeviceInfo])
def api_list_wemo_devices():
    """
    List currently known WeMo devices (without forcing rediscovery).
    """
    with device_lock:
        current_devices = list(devices.values())
    return [wemo_device_to_info(d) for d in current_devices]


@app.get("/devices/{device_id}", response_model=DeviceInfo)
def api_get_wemo_device(device_id: str):
    device = get_wemo_device_or_404(device_id)
    return wemo_device_to_info(device)


@app.post("/devices/{device_id}/on", response_model=DeviceInfo)
def api_wemo_on(device_id: str):
    device = get_wemo_device_or_404(device_id)
    try:
        device.on()
        info = wemo_device_to_info(device)
        # Broadcast state change event
        broadcast_event("wemo_state_change", {
            "deviceId": device_id,
            "action": "on",
            "state": info.dict()
        })
    except Exception as e:
        logger.exception("Error turning WeMo device ON")
        raise HTTPException(status_code=500, detail=str(e))
    return wemo_device_to_info(device)


@app.post("/devices/{device_id}/off", response_model=DeviceInfo)
def api_wemo_off(device_id: str):
    device = get_wemo_device_or_404(device_id)
    try:
        device.off()
        info = wemo_device_to_info(device)
        # Broadcast state change event
        broadcast_event("wemo_state_change", {
            "deviceId": device_id,
            "action": "off",
            "state": info.dict()
        })
    except Exception as e:
        logger.exception("Error turning WeMo device OFF")
        raise HTTPException(status_code=500, detail=str(e))
    return wemo_device_to_info(device)


@app.post("/devices/{device_id}/toggle", response_model=DeviceInfo)
def api_wemo_toggle(device_id: str):
    device = get_wemo_device_or_404(device_id)
    try:
        device.toggle()
        info = wemo_device_to_info(device)
        # Broadcast state change event
        broadcast_event("wemo_state_change", {
            "deviceId": device_id,
            "action": "toggle",
            "state": info.dict()
        })
    except Exception as e:
        logger.exception("Error toggling WeMo device")
        raise HTTPException(status_code=500, detail=str(e))
    return wemo_device_to_info(device)


@app.post("/devices/{device_id}/rename", response_model=DeviceInfo)
def api_wemo_rename(device_id: str, body: RenameRequest):
    """
    Rename a WeMo device (and update the in-memory registry).
    """
    new_name = body.name.strip()
    if not new_name:
        raise HTTPException(status_code=400, detail="New name must not be empty")

    device = get_wemo_device_or_404(device_id)

    try:
        device.name = new_name
    except Exception as e:
        logger.exception("Error renaming WeMo device")
        raise HTTPException(status_code=500, detail=str(e))

    with device_lock:
        devices.pop(device_id, None)
        new_key = getattr(device, "serialnumber", None) or device.name
        devices[new_key] = device

    return wemo_device_to_info(device)


# -----------------------------
# Govee routes
# -----------------------------
@app.post("/govee/discover", response_model=List[GoveeDeviceInfo])
def api_govee_discover():
    """
    Fetch devices from Govee cloud and return their current state.
    """
    try:
        govee_discover_devices()
    except Exception as e:
        logger.exception("Error discovering Govee devices")
        raise HTTPException(status_code=500, detail=f"Govee discovery failed: {e}")

    infos: List[GoveeDeviceInfo] = []
    with govee_lock:
        keys = list(govee_devices.keys())
    for key in keys:
        try:
            infos.append(govee_get_state(key))
        except Exception as e:
            logger.warning("Failed to fetch state for Govee device %s: %s", key, e)
    return infos


@app.get("/govee/devices", response_model=List[GoveeDeviceInfo])
def api_govee_list_devices():
    """
    List cached Govee devices with fresh state.
    """
    if not govee_devices:
        govee_discover_devices()

    infos: List[GoveeDeviceInfo] = []
    with govee_lock:
        keys = list(govee_devices.keys())
    for key in keys:
        try:
            infos.append(govee_get_state(key))
        except Exception as e:
            logger.warning("Failed to fetch state for Govee device %s: %s", key, e)
    return infos


@app.post("/govee/devices/{device_id}/{action}", response_model=GoveeDeviceInfo)
def api_govee_control_device(device_id: str, action: str):
    """
    Turn a Govee device on/off.
    """
    try:
        info = govee_control(device_id, action)
        # Broadcast state change event
        broadcast_event("govee_state_change", {
            "deviceId": device_id,
            "action": action,
            "state": info.dict()
        })
        return info
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error controlling Govee device")
        raise HTTPException(status_code=500, detail=f"Govee control failed: {e}")
