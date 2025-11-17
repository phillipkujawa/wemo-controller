from js import Response, Headers, fetch, Object
import json

async def on_fetch(request, env):
    """Cloudflare Python Worker for Govee API"""

    # Get request details
    url = str(request.url)
    method = str(request.method)

    # CORS headers
    headers_dict = {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type",
        "Content-Type": "application/json"
    }

    # Handle OPTIONS
    if method == "OPTIONS":
        return Response.new("", status=204, headers=Headers.new(headers_dict))

    # Parse path
    if "workers.dev" in url:
        path = url.split("workers.dev")[1]
    else:
        path = "/"

    # Route: Health check
    if path == "/" or path == "":
        return make_json_response({
            "status": "ok",
            "message": "Govee Controller API",
            "version": "1.0.0"
        }, headers_dict)

    # Route: Discover Govee devices
    if path == "/govee/discover" and method == "POST":
        try:
            # Call Govee API
            govee_url = "https://openapi.api.govee.com/router/api/v1/user/devices"
            govee_headers = Headers.new({
                "Govee-API-Key": env.GOVEE_API_KEY,
                "Content-Type": "application/json"
            })

            govee_response = await fetch(govee_url, Object.new(method="GET", headers=govee_headers))
            data = await govee_response.json()

            if data.code != 200:
                return make_json_response({"error": "Govee API error", "details": data}, headers_dict, 502)

            devices = data.data or []

            # Cache in KV
            await env.DEVICES_KV.put("govee_devices", json.dumps(devices))

            # Return simplified device list
            result = []
            for device in devices:
                result.append({
                    "id": f"{device['sku']}|{device['device']}",
                    "name": device.get("deviceName", "Unknown"),
                    "model": device["sku"],
                    "device": device["device"],
                    "controllable": True,
                    "state": "unknown"
                })

            return make_json_response(result, headers_dict)

        except Exception as e:
            return make_json_response({"error": str(e)}, headers_dict, 500)

    # Route: List devices
    if path == "/govee/devices" and method == "GET":
        try:
            cached = await env.DEVICES_KV.get("govee_devices")

            if not cached:
                return make_json_response([], headers_dict)

            devices = json.loads(cached)

            result = []
            for device in devices:
                result.append({
                    "id": f"{device['sku']}|{device['device']}",
                    "name": device.get("deviceName", "Unknown"),
                    "model": device["sku"],
                    "device": device["device"],
                    "controllable": True,
                    "state": "unknown"
                })

            return make_json_response(result, headers_dict)

        except Exception as e:
            return make_json_response({"error": str(e)}, headers_dict, 500)

    # Route: Control device
    if "/govee/devices/" in path and method == "POST":
        try:
            # Parse device_id and action from path
            # Path format: /govee/devices/{device_id}/{action}
            parts = path.split("/govee/devices/")[1].split("/")

            if len(parts) < 2:
                return make_json_response({"error": "Invalid path format"}, headers_dict, 400)

            device_id = parts[0]
            action = parts[1].lower()

            if action not in ["on", "off"]:
                return make_json_response({"error": "Action must be 'on' or 'off'"}, headers_dict, 400)

            # Parse device_id
            device_parts = device_id.split("|")
            if len(device_parts) != 2:
                return make_json_response({"error": "Invalid device ID"}, headers_dict, 400)

            sku = device_parts[0]
            device = device_parts[1]
            value = 1 if action == "on" else 0

            # Call Govee control API
            control_url = "https://openapi.api.govee.com/router/api/v1/device/control"
            control_body = {
                "requestId": "req-" + str(hash(device_id))[-8:],
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

            control_headers = Headers.new({
                "Govee-API-Key": env.GOVEE_API_KEY,
                "Content-Type": "application/json"
            })

            control_response = await fetch(
                control_url,
                Object.new(
                    method="POST",
                    headers=control_headers,
                    body=json.dumps(control_body)
                )
            )

            result_data = await control_response.json()

            if result_data.get("code") != 200:
                return make_json_response({
                    "error": "Govee control failed",
                    "details": result_data
                }, headers_dict, 502)

            return make_json_response({
                "id": device_id,
                "model": sku,
                "device": device,
                "state": action,
                "success": True
            }, headers_dict)

        except Exception as e:
            return make_json_response({"error": str(e)}, headers_dict, 500)

    # Not found
    return make_json_response({"error": "Not found", "path": path}, headers_dict, 404)


def make_json_response(data, headers_dict, status=200):
    """Helper to create JSON response"""
    return Response.new(
        json.dumps(data),
        status=status,
        headers=Headers.new(headers_dict)
    )
