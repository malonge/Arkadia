/**
 * Arkadia API client.
 *
 * All calls go to /api/* (proxied to FastAPI in dev; served from the same
 * origin in production).  The API key is read from localStorage so it
 * never appears in source code.
 */

// ---------------------------------------------------------------------------
// Location (hardcoded until GPS is integrated)
// ---------------------------------------------------------------------------

export const LOCATION = {
  lat:  34.0792184,
  lon: -118.3549672,
  /** Compact display string, e.g. "34.0792°N, 118.3550°W" */
  label: '34.0792°N, 118.3550°W',
};

// ---------------------------------------------------------------------------
// Audio calibration
// ---------------------------------------------------------------------------

/**
 * Approximate offset from dBFS to dB SPL for the INMP441 microphone.
 * INMP441 sensitivity: −26 dBFS at 94 dB SPL (1 kHz, 1 Pa)
 * → offset = 94 − (−26) = 120
 *
 * Apply as:  dB_SPL ≈ dBFS + INMP441_OFFSET
 * Label results with "~" to indicate they are uncalibrated.
 */
export const INMP441_OFFSET = 120;

/** Convert a dBFS value to approximate dB SPL. */
export function dbfsToDB(dbfs) {
  return dbfs + INMP441_OFFSET;
}

// ---------------------------------------------------------------------------
// Threshold helpers
// ---------------------------------------------------------------------------

/**
 * Return a status string for a numeric value given an ordered threshold table.
 *
 * @param {number} value
 * @param {Array<[number, number, string]>} ranges  Each entry: [lo, hi, status]
 *   where lo is inclusive and hi is exclusive.  Ranges should be exhaustive.
 * @returns {'good'|'ok'|'warn'|'danger'|'unknown'}
 */
export function statusFor(value, ranges) {
  if (value == null || isNaN(value)) return 'unknown';
  for (const [lo, hi, status] of ranges) {
    if (value >= lo && value < hi) return status;
  }
  return 'unknown';
}

export const THRESHOLDS = {
  /** Temperature in °C */
  temperature_c: [
    [-Infinity, 10,  'danger'],
    [10,        16,  'warn'  ],
    [16,        26,  'good'  ],
    [26,        30,  'ok'    ],
    [30,  Infinity,  'danger'],
  ],
  /** Relative humidity in % */
  humidity_pct: [
    [-Infinity, 25,  'warn'  ],
    [25,        30,  'ok'    ],
    [30,        60,  'good'  ],
    [60,        70,  'ok'    ],
    [70,  Infinity,  'warn'  ],
  ],
  /** Atmospheric pressure in hPa */
  pressure_hpa: [
    [-Infinity, 980,  'warn'  ],
    [980,       990,  'ok'    ],
    [990,       1025, 'good'  ],
    [1025,      1035, 'ok'    ],
    [1035, Infinity,  'warn'  ],
  ],
  /** CO₂ in ppm */
  co2_ppm: [
    [-Infinity, 800,  'good'  ],
    [800,       1000, 'ok'    ],
    [1000,      1200, 'warn'  ],
    [1200, Infinity,  'danger'],
  ],
  /** Audio RMS dBFS */
  db_level: [
    [-Infinity, -60,  'ok'    ],
    [-60,       -30,  'good'  ],
    [-30,       -10,  'warn'  ],
    [-10,  Infinity,  'danger'],
  ],
};

// ---------------------------------------------------------------------------
// Time formatting
// ---------------------------------------------------------------------------

/**
 * Return a human-readable relative time string for an ISO 8601 timestamp.
 * e.g. "just now", "14s ago", "2m ago", "1h ago"
 */
export function formatRelativeTime(isoString) {
  if (!isoString) return null;
  const diffMs = Date.now() - new Date(isoString).getTime();
  const s = Math.max(0, Math.floor(diffMs / 1000));
  if (s < 10)  return 'just now';
  if (s < 60)  return `${s}s ago`;
  const m = Math.floor(s / 60);
  if (m < 60)  return `${m}m ago`;
  const h = Math.floor(m / 60);
  return `${h}h ago`;
}

/**
 * Format a Date as HH:MM:SS.
 */
export function formatHMS(date) {
  return date.toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

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
