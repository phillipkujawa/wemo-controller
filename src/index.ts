import { Hono } from 'hono';
import { cors } from 'hono/cors';

type Bindings = {
  GOVEE_API_KEY: string;
  GOVEE_API_BASE: string;
  EVENTS: DurableObjectNamespace;
  DEVICES_KV: KVNamespace;
};

const app = new Hono<{ Bindings: Bindings }>();

// Enable CORS
app.use('/*', cors());

// Govee API helper
async function goveeRequest(
  env: Bindings,
  path: string,
  method: string = 'GET',
  body?: any
) {
  const url = `${env.GOVEE_API_BASE}${path}`;
  const headers = {
    'Govee-API-Key': env.GOVEE_API_KEY,
    'Content-Type': 'application/json',
  };

  const response = await fetch(url, {
    method,
    headers,
    body: body ? JSON.stringify(body) : undefined,
  });

  if (!response.ok) {
    throw new Error(`Govee API error: ${response.status} ${await response.text()}`);
  }

  return response.json();
}

// Health check
app.get('/', (c) => {
  return c.json({
    status: 'ok',
    message: 'WeMo + Govee Controller API',
    version: '2.0.0',
    platform: 'Cloudflare Workers',
  });
});

// Discover Govee devices
app.post('/govee/discover', async (c) => {
  try {
    const data = await goveeRequest(c.env, '/router/api/v1/user/devices', 'GET');

    if (data.code !== 200) {
      return c.json({ error: 'Failed to discover devices', details: data }, 502);
    }

    const devices = data.data || [];

    // Cache devices in KV
    await c.env.DEVICES_KV.put('govee_devices', JSON.stringify(devices), {
      expirationTtl: 3600, // 1 hour
    });

    // Fetch state for each device
    const devicesWithState = await Promise.all(
      devices.map(async (device: any) => {
        try {
          const stateData = await goveeRequest(
            c.env,
            '/router/api/v1/device/state',
            'POST',
            {
              requestId: crypto.randomUUID(),
              payload: {
                sku: device.sku,
                device: device.device,
              },
            }
          );

          const capabilities = stateData.payload?.capabilities || [];
          let powerState = 'unknown';
          let online = null;

          for (const cap of capabilities) {
            if (cap.type === 'devices.capabilities.online') {
              online = Boolean(cap.state?.value);
            }
            if (
              cap.type === 'devices.capabilities.on_off' &&
              cap.instance === 'powerSwitch'
            ) {
              powerState = cap.state?.value === 1 ? 'on' : 'off';
            }
          }

          return {
            id: `${device.sku}|${device.device}`,
            name: stateData.payload?.deviceName || device.deviceName,
            model: device.sku,
            device: device.device,
            controllable: true,
            retrievable: true,
            state: powerState,
            online,
          };
        } catch (error) {
          console.error(`Error fetching state for ${device.sku}:`, error);
          return {
            id: `${device.sku}|${device.device}`,
            name: device.deviceName,
            model: device.sku,
            device: device.device,
            controllable: true,
            retrievable: true,
            state: 'unknown',
            online: null,
          };
        }
      })
    );

    return c.json(devicesWithState);
  } catch (error: any) {
    console.error('Error discovering Govee devices:', error);
    return c.json({ error: error.message }, 500);
  }
});

// List Govee devices
app.get('/govee/devices', async (c) => {
  try {
    // Try to get from cache first
    const cached = await c.env.DEVICES_KV.get('govee_devices');
    if (!cached) {
      // If no cache, trigger discovery
      return c.redirect('/govee/discover');
    }

    const devices = JSON.parse(cached);

    // Fetch current state
    const devicesWithState = await Promise.all(
      devices.map(async (device: any) => {
        try {
          const stateData = await goveeRequest(
            c.env,
            '/router/api/v1/device/state',
            'POST',
            {
              requestId: crypto.randomUUID(),
              payload: {
                sku: device.sku,
                device: device.device,
              },
            }
          );

          const capabilities = stateData.payload?.capabilities || [];
          let powerState = 'unknown';
          let online = null;

          for (const cap of capabilities) {
            if (cap.type === 'devices.capabilities.online') {
              online = Boolean(cap.state?.value);
            }
            if (
              cap.type === 'devices.capabilities.on_off' &&
              cap.instance === 'powerSwitch'
            ) {
              powerState = cap.state?.value === 1 ? 'on' : 'off';
            }
          }

          return {
            id: `${device.sku}|${device.device}`,
            name: stateData.payload?.deviceName || device.deviceName,
            model: device.sku,
            device: device.device,
            controllable: true,
            retrievable: true,
            state: powerState,
            online,
          };
        } catch (error) {
          return {
            id: `${device.sku}|${device.device}`,
            name: device.deviceName,
            model: device.sku,
            device: device.device,
            controllable: true,
            retrievable: true,
            state: 'unknown',
            online: null,
          };
        }
      })
    );

    return c.json(devicesWithState);
  } catch (error: any) {
    console.error('Error listing Govee devices:', error);
    return c.json({ error: error.message }, 500);
  }
});

// Control Govee device
app.post('/govee/devices/:deviceId/:action', async (c) => {
  try {
    const deviceId = c.req.param('deviceId');
    const action = c.req.param('action').toLowerCase();

    if (!['on', 'off'].includes(action)) {
      return c.json({ error: 'Invalid action. Use "on" or "off"' }, 400);
    }

    const [sku, device] = deviceId.split('|');
    if (!sku || !device) {
      return c.json({ error: 'Invalid device ID format' }, 400);
    }

    const value = action === 'on' ? 1 : 0;

    // Send control command
    await goveeRequest(c.env, '/router/api/v1/device/control', 'POST', {
      requestId: crypto.randomUUID(),
      payload: {
        sku,
        device,
        capability: {
          type: 'devices.capabilities.on_off',
          instance: 'powerSwitch',
          value,
        },
      },
    });

    // Fetch updated state
    const stateData = await goveeRequest(
      c.env,
      '/router/api/v1/device/state',
      'POST',
      {
        requestId: crypto.randomUUID(),
        payload: { sku, device },
      }
    );

    const capabilities = stateData.payload?.capabilities || [];
    let powerState = 'unknown';
    let online = null;

    for (const cap of capabilities) {
      if (cap.type === 'devices.capabilities.online') {
        online = Boolean(cap.state?.value);
      }
      if (
        cap.type === 'devices.capabilities.on_off' &&
        cap.instance === 'powerSwitch'
      ) {
        powerState = cap.state?.value === 1 ? 'on' : 'off';
      }
    }

    return c.json({
      id: deviceId,
      name: stateData.payload?.deviceName,
      model: sku,
      device,
      controllable: true,
      retrievable: true,
      state: powerState,
      online,
    });
  } catch (error: any) {
    console.error('Error controlling Govee device:', error);
    return c.json({ error: error.message }, 500);
  }
});

// Server-Sent Events endpoint
app.get('/events', async (c) => {
  // Get Durable Object stub
  const id = c.env.EVENTS.idFromName('global-events');
  const stub = c.env.EVENTS.get(id);

  // Forward request to Durable Object
  return stub.fetch(c.req.raw);
});

// Export Durable Object for SSE
export class EventsManager {
  private state: DurableObjectState;
  private sessions: Set<any>;

  constructor(state: DurableObjectState, env: Bindings) {
    this.state = state;
    this.sessions = new Set();
  }

  async fetch(request: Request) {
    // SSE endpoint
    if (request.url.endsWith('/events')) {
      const { readable, writable } = new TransformStream();
      const writer = writable.getWriter();
      const encoder = new TextEncoder();

      // Send initial connection message
      writer.write(
        encoder.encode('event: connected\ndata: {"message":"Connected to event stream"}\n\n')
      );

      // Store session
      this.sessions.add(writer);

      // Keep alive
      const keepAliveInterval = setInterval(() => {
        writer
          .write(
            encoder.encode(
              `event: keepalive\ndata: {"timestamp":"${new Date().toISOString()}"}\n\n`
            )
          )
          .catch(() => {
            clearInterval(keepAliveInterval);
            this.sessions.delete(writer);
          });
      }, 30000); // 30 seconds

      // Return SSE response
      return new Response(readable, {
        headers: {
          'Content-Type': 'text/event-stream',
          'Cache-Control': 'no-cache',
          Connection: 'keep-alive',
        },
      });
    }

    return new Response('Not found', { status: 404 });
  }

  async broadcast(event: { type: string; data: any }) {
    const encoder = new TextEncoder();
    const message = `event: ${event.type}\ndata: ${JSON.stringify(event.data)}\n\n`;

    const deadSessions: any[] = [];

    for (const session of this.sessions) {
      try {
        await session.write(encoder.encode(message));
      } catch (error) {
        deadSessions.push(session);
      }
    }

    // Clean up dead sessions
    deadSessions.forEach((session) => this.sessions.delete(session));
  }
}

export default app;
