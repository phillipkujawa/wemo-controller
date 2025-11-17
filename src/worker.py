from js import Response, Headers, fetch
import json
import uuid

async def on_fetch(request, env):
    """Main request handler for Cloudflare Python Worker"""

    url = request.url
    method = request.method

    # CORS headers
    cors_headers = {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type",
        "Content-Type": "application/json"
    }

    # Handle CORS preflight
    if method == "OPTIONS":
        return Response.new(None, status=204, headers=Headers.new(cors_headers))

    # Root endpoint
    if url.endswith("/") or url.endswith(env.WORKER_URL):
        return json_response({
            "status": "ok",
            "message": "WeMo + Govee Controller API",
            "version": "2.0.0",
            "platform": "Cloudflare Python Workers"
        }, cors_headers)

    # Govee discover endpoint
    if "/govee/discover" in url and method == "POST":
        return await govee_discover(env, cors_headers)

    # Govee list devices
    if "/govee/devices" in url and method == "GET":
        return await govee_list_devices(env, cors_headers)

    # Govee control device
    if "/govee/devices/" in url and method == "POST":
        parts = url.split("/govee/devices/")[1].split("/")
        if len(parts) >= 2:
            device_id = parts[0]
            action = parts[1]
            return await govee_control(env, device_id, action, cors_headers)

    # Not found
    return json_response({"error": "Not found"}, cors_headers, 404)


async def govee_request(env, path, method="GET", body=None):
    """Make request to Govee API"""
    url = f"https://openapi.api.govee.com{path}"

    headers = {
        "Govee-API-Key": env.GOVEE_API_KEY,
        "Content-Type": "application/json"
    }

    options = {
        "method": method,
        "headers": Headers.new(headers)
    }

    if body:
        options["body"] = json.dumps(body)

    response = await fetch(url, options)
    data = await response.json()

    return data


async def govee_discover(env, cors_headers):
    """Discover Govee devices"""
    try:
        data = await govee_request(env, "/router/api/v1/user/devices", "GET")

        if data.get("code") != 200:
            return json_response(
                {"error": "Failed to discover devices", "details": data},
                cors_headers,
                502
            )

        devices = data.get("data", [])

        # Cache in KV
        await env.DEVICES_KV.put("govee_devices", json.dumps(devices), expirationTtl=3600)

        # Fetch state for each device
        devices_with_state = []
        for device in devices:
            try:
                sku = device["sku"]
                device_id = device["device"]

                state_data = await govee_request(
                    env,
                    "/router/api/v1/device/state",
                    "POST",
                    {
                        "requestId": generate_uuid(),
                        "payload": {
                            "sku": sku,
                            "device": device_id
                        }
                    }
                )

                capabilities = state_data.get("payload", {}).get("capabilities", [])
                power_state = "unknown"
                online = None

                for cap in capabilities:
                    if cap.get("type") == "devices.capabilities.online":
                        online = bool(cap.get("state", {}).get("value"))
                    if cap.get("type") == "devices.capabilities.on_off" and cap.get("instance") == "powerSwitch":
                        power_state = "on" if cap.get("state", {}).get("value") == 1 else "off"

                devices_with_state.append({
                    "id": f"{sku}|{device_id}",
                    "name": state_data.get("payload", {}).get("deviceName") or device.get("deviceName"),
                    "model": sku,
                    "device": device_id,
                    "controllable": True,
                    "retrievable": True,
                    "state": power_state,
                    "online": online
                })
            except Exception as e:
                # Add device with unknown state on error
                devices_with_state.append({
                    "id": f"{device['sku']}|{device['device']}",
                    "name": device.get("deviceName"),
                    "model": device["sku"],
                    "device": device["device"],
                    "controllable": True,
                    "retrievable": True,
                    "state": "unknown",
                    "online": None
                })

        return json_response(devices_with_state, cors_headers)

    except Exception as e:
        return json_response({"error": str(e)}, cors_headers, 500)


async def govee_list_devices(env, cors_headers):
    """List Govee devices from cache"""
    try:
        # Get from cache
        cached = await env.DEVICES_KV.get("govee_devices")

        if not cached:
            # Trigger discovery
            return await govee_discover(env, cors_headers)

        devices = json.loads(cached)

        # Fetch current state
        devices_with_state = []
        for device in devices:
            try:
                sku = device["sku"]
                device_id = device["device"]

                state_data = await govee_request(
                    env,
                    "/router/api/v1/device/state",
                    "POST",
                    {
                        "requestId": generate_uuid(),
                        "payload": {
                            "sku": sku,
                            "device": device_id
                        }
                    }
                )

                capabilities = state_data.get("payload", {}).get("capabilities", [])
                power_state = "unknown"
                online = None

                for cap in capabilities:
                    if cap.get("type") == "devices.capabilities.online":
                        online = bool(cap.get("state", {}).get("value"))
                    if cap.get("type") == "devices.capabilities.on_off" and cap.get("instance") == "powerSwitch":
                        power_state = "on" if cap.get("state", {}).get("value") == 1 else "off"

                devices_with_state.append({
                    "id": f"{sku}|{device_id}",
                    "name": state_data.get("payload", {}).get("deviceName") or device.get("deviceName"),
                    "model": sku,
                    "device": device_id,
                    "controllable": True,
                    "retrievable": True,
                    "state": power_state,
                    "online": online
                })
            except Exception:
                devices_with_state.append({
                    "id": f"{device['sku']}|{device['device']}",
                    "name": device.get("deviceName"),
                    "model": device["sku"],
                    "device": device["device"],
                    "controllable": True,
                    "retrievable": True,
                    "state": "unknown",
                    "online": None
                })

        return json_response(devices_with_state, cors_headers)

    except Exception as e:
        return json_response({"error": str(e)}, cors_headers, 500)


async def govee_control(env, device_id, action, cors_headers):
    """Control Govee device"""
    try:
        action = action.lower()
        if action not in ["on", "off"]:
            return json_response({"error": "Invalid action. Use 'on' or 'off'"}, cors_headers, 400)

        parts = device_id.split("|")
        if len(parts) != 2:
            return json_response({"error": "Invalid device ID format"}, cors_headers, 400)

        sku, device = parts
        value = 1 if action == "on" else 0

        # Send control command
        await govee_request(
            env,
            "/router/api/v1/device/control",
            "POST",
            {
                "requestId": generate_uuid(),
                "payload": {
                    "sku": sku,
                    "device": device,
                    "capability": {
                        "type": "devices.capabilities.on_off",
                        "instance": "powerSwitch",
                        "value": value
                    }
                }
            }
        )

        # Fetch updated state
        state_data = await govee_request(
            env,
            "/router/api/v1/device/state",
            "POST",
            {
                "requestId": generate_uuid(),
                "payload": {"sku": sku, "device": device}
            }
        )

        capabilities = state_data.get("payload", {}).get("capabilities", [])
        power_state = "unknown"
        online = None

        for cap in capabilities:
            if cap.get("type") == "devices.capabilities.online":
                online = bool(cap.get("state", {}).get("value"))
            if cap.get("type") == "devices.capabilities.on_off" and cap.get("instance") == "powerSwitch":
                power_state = "on" if cap.get("state", {}).get("value") == 1 else "off"

        return json_response({
            "id": device_id,
            "name": state_data.get("payload", {}).get("deviceName"),
            "model": sku,
            "device": device,
            "controllable": True,
            "retrievable": True,
            "state": power_state,
            "online": online
        }, cors_headers)

    except Exception as e:
        return json_response({"error": str(e)}, cors_headers, 500)


def json_response(data, headers, status=200):
    """Create JSON response"""
    return Response.new(
        json.dumps(data),
        status=status,
        headers=Headers.new(headers)
    )


def generate_uuid():
    """Generate a simple UUID"""
    return str(uuid.uuid4())
