/**
 * Arkadia API client.
 *
 * All calls go to /api/* (proxied to FastAPI in dev; served from the same
 * origin in production).  The API key is read from localStorage so it
 * never appears in source code.
 */

const BASE = '/api';
const KEY_STORAGE = 'arkadia_api_key';

// ---------------------------------------------------------------------------
// Key management
// ---------------------------------------------------------------------------

export function getApiKey() {
  return localStorage.getItem(KEY_STORAGE) ?? '';
}

export function setApiKey(key) {
  localStorage.setItem(KEY_STORAGE, key);
}

export function clearApiKey() {
  localStorage.removeItem(KEY_STORAGE);
}

// ---------------------------------------------------------------------------
// HTTP helpers
// ---------------------------------------------------------------------------

function headers() {
  return {
    'X-API-Key': getApiKey(),
    'Content-Type': 'application/json',
  };
}

async function get(path) {
  const res = await fetch(`${BASE}${path}`, { headers: headers() });
  if (!res.ok) {
    const err = new Error(`HTTP ${res.status} — ${path}`);
    err.status = res.status;
    throw err;
  }
  return res.json();
}

// ---------------------------------------------------------------------------
// Endpoints
// ---------------------------------------------------------------------------

/** Returns all sensor readings keyed by sensor_id. */
export function fetchSensors() {
  return get('/sensors');
}

/** Returns the latest reading for one sensor (throws on 404/503). */
export function fetchSensor(sensorId) {
  return get(`/sensors/${sensorId}`);
}

/** Returns staleness and connectivity metadata for one sensor. */
export function fetchSensorStatus(sensorId) {
  return get(`/sensors/${sensorId}/status`);
}

/** Returns service health (broker connected, uptime). */
export function fetchHealth() {
  return get('/health');
}

/** Returns version info. */
export function fetchVersion() {
  return get('/version');
}

// ---------------------------------------------------------------------------
// WebSocket audio stream
// ---------------------------------------------------------------------------

/**
 * Open a WebSocket connection to the real-time audio stream.
 *
 * @param {(frame: object) => void} onFrame   - called for each parsed frame
 * @param {(status: string) => void} onStatus - called with "connected" | "disconnected" | "error"
 * @returns {{ close: () => void }}            - handle to close the connection
 */
export function createAudioStream(onFrame, onStatus) {
  const key = getApiKey();
  const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
  const url = `${protocol}//${location.host}/ws/audio/stream?api_key=${encodeURIComponent(key)}`;

  let ws = null;
  let closed = false;
  let retryDelay = 1000;

  function connect() {
    if (closed) return;
    ws = new WebSocket(url);

    ws.addEventListener('open', () => {
      retryDelay = 1000;
      onStatus('connected');
    });

    ws.addEventListener('message', (evt) => {
      try {
        onFrame(JSON.parse(evt.data));
      } catch {
        // malformed frame — ignore
      }
    });

    ws.addEventListener('close', () => {
      onStatus('disconnected');
      if (!closed) {
        setTimeout(connect, retryDelay);
        retryDelay = Math.min(retryDelay * 2, 30_000);
      }
    });

    ws.addEventListener('error', () => {
      onStatus('error');
    });
  }

  connect();

  return {
    close() {
      closed = true;
      ws?.close();
    },
  };
}
