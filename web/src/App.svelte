<script>
  import { onMount } from 'svelte';
  import {
    getApiKey,
    dbfsToDB,
    statusFor,
    THRESHOLDS,
    fetchHealth,
    fetchSensors,
    fetchSensorStatus,
    createAudioStream,
    formatRelativeTime,
    formatHMS,
  } from './api.js';

  import Header        from './components/Header.svelte';
  import SensorCard    from './components/SensorCard.svelte';
  import StatusBar     from './components/StatusBar.svelte';
  import SettingsModal from './components/SettingsModal.svelte';
  import ReadingRow       from './components/ReadingRow.svelte';
  import TemperatureGauge from './components/TemperatureGauge.svelte';
  import BarMeter         from './components/BarMeter.svelte';
  import EQVisualizer     from './components/EQVisualizer.svelte';
  import WaveformScope    from './components/WaveformScope.svelte';

  // ---------------------------------------------------------------------------
  // Settings gate
  // ---------------------------------------------------------------------------
  let apiKey      = $state(getApiKey());
  let showSettings = $state(!getApiKey());

  function handleSave(key) {
    apiKey = key;
    showSettings = false;
    startBoot();
  }

  function openSettings() {
    showSettings = true;
  }

  // ---------------------------------------------------------------------------
  // Boot sequence
  // ---------------------------------------------------------------------------
  const BOOT_LINES = [
    'ARKADIA SYSTEM v1.1.0',
    'INITIALISING SENSORS…',
    'CONNECTING TO BROKER…',
    'LOADING DASHBOARD…',
    '',
  ];

  let booting   = $state(true);
  let bootLines = $state([]);
  let bootDone  = $state(false);

  function startBoot() {
    booting   = true;
    bootLines = [];
    bootDone  = false;

    let lineIdx = 0, charIdx = 0, current = '';

    function tick() {
      if (lineIdx >= BOOT_LINES.length) {
        bootDone = true;
        setTimeout(() => { booting = false; }, 300);
        return;
      }
      const line = BOOT_LINES[lineIdx];
      if (charIdx < line.length) {
        current += line[charIdx];
        bootLines = [...bootLines.slice(0, lineIdx), current];
        charIdx++;
        setTimeout(tick, 28);
      } else {
        bootLines = [...bootLines.slice(0, lineIdx), current];
        lineIdx++; charIdx = 0; current = '';
        setTimeout(tick, lineIdx === BOOT_LINES.length ? 400 : 80);
      }
    }
    tick();
  }

  // ---------------------------------------------------------------------------
  // Sensor state
  // ---------------------------------------------------------------------------

  function makeSensor(title) {
    return { title, connectivity: 'unknown', lastSeen: null, stale: false, readings: null };
  }

  let bme280  = $state(makeSensor('CLIMATE'));
  let scd40   = $state(makeSensor('AIR QUALITY'));
  let inmp441 = $state(makeSensor('AUDIO'));

  // Derived display values for BME280
  const tempC  = $derived(bme280.readings?.temperature_c ?? null);
  const humPct = $derived(bme280.readings?.humidity_pct  ?? null);
  const presHpa = $derived(bme280.readings?.pressure_hpa ?? null);

  const tempStatus = $derived(statusFor(tempC,   THRESHOLDS.temperature_c));
  const humStatus  = $derived(statusFor(humPct,  THRESHOLDS.humidity_pct));
  const presStatus = $derived(statusFor(presHpa, THRESHOLDS.pressure_hpa));

  // Derived display values for SCD40
  const co2Ppm     = $derived(scd40.readings?.co2_ppm      ?? null);
  const scdTempC   = $derived(scd40.readings?.temperature_c ?? null);
  const scdHumPct  = $derived(scd40.readings?.humidity_pct  ?? null);

  const co2Status     = $derived(statusFor(co2Ppm,    THRESHOLDS.co2_ppm));
  const scdTempStatus = $derived(statusFor(scdTempC,  THRESHOLDS.temperature_c));
  const scdHumStatus  = $derived(statusFor(scdHumPct, THRESHOLDS.humidity_pct));

  // ---------------------------------------------------------------------------
  // WebSocket audio stream
  // ---------------------------------------------------------------------------

  // Plain mutable variable — not $state — to avoid deep-tracking a large
  // object (waveform has 2400 samples) at 20 Hz.
  let latestAudioFrame = null;
  let wsConnected      = $state(false);

  // Getter function passed to canvas components so they always read the
  // current frame from inside their rAF loops without needing reactivity.
  function getAudioFrame() { return latestAudioFrame; }

  // ---------------------------------------------------------------------------
  // Polling
  // ---------------------------------------------------------------------------
  let brokerConnected = $state(false);
  let lastPoll        = $state(null);
  let pollError       = $state(false);
  let retryDelay      = 5_000;
  let pollTimer       = null;

  async function poll() {
    const [healthRes, sensorsRes, s1Res, s2Res, s3Res] = await Promise.allSettled([
      fetchHealth(),
      fetchSensors(),
      fetchSensorStatus('bme280'),
      fetchSensorStatus('scd40'),
      fetchSensorStatus('inmp441'),
    ]);

    // Broker health
    if (healthRes.status === 'fulfilled') {
      brokerConnected = healthRes.value.broker_connected;
    }

    // Latest readings
    if (sensorsRes.status === 'fulfilled') {
      const d = sensorsRes.value;
      if (d.bme280)  bme280.readings  = d.bme280.readings;
      if (d.scd40)   scd40.readings   = d.scd40.readings;
      if (d.inmp441) inmp441.readings = d.inmp441.readings;
    }

    // Per-sensor status (connectivity + staleness + last_seen)
    const applyStatus = (res, sensor) => {
      if (res.status === 'fulfilled') {
        sensor.connectivity = res.value.connectivity;
        sensor.stale        = res.value.stale;
        sensor.lastSeen     = formatRelativeTime(res.value.last_seen);
      }
    };
    applyStatus(s1Res, bme280);
    applyStatus(s2Res, scd40);
    applyStatus(s3Res, inmp441);

    // Mark overall poll result
    const anyFailed = [healthRes, sensorsRes].some(r => r.status === 'rejected');
    if (anyFailed) {
      pollError  = true;
      retryDelay = Math.min(retryDelay * 2, 60_000);
    } else {
      pollError  = false;
      retryDelay = 30_000;
      lastPoll   = formatHMS(new Date());
    }
  }

  function schedulePoll() {
    poll().finally(() => {
      pollTimer = setTimeout(schedulePoll, retryDelay);
    });
  }

  // ---------------------------------------------------------------------------
  // Lifecycle
  // ---------------------------------------------------------------------------
  onMount(() => {
    if (apiKey) startBoot();

    // Start polling after boot animation
    const delay = apiKey ? 1800 : 0;
    pollTimer = setTimeout(schedulePoll, delay);

    // Open WebSocket audio stream immediately (it reconnects automatically)
    let audioStream = null;
    if (apiKey) {
      audioStream = createAudioStream(
        (frame) => { latestAudioFrame = frame; },
        (status) => { wsConnected = status === 'connected'; },
      );
    }

    return () => {
      if (pollTimer) clearTimeout(pollTimer);
      audioStream?.close();
    };
  });
</script>

<!-- Settings modal -->
{#if showSettings}
  <SettingsModal onSave={handleSave} />
{/if}

<!-- Boot sequence overlay -->
{#if !showSettings && booting}
  <div class="boot-screen" aria-live="polite">
    <div class="boot-lines">
      {#each bootLines as line, i}
        <div class="boot-line">
          <span class="dim">&gt;</span>
          {line}{#if i === bootLines.length - 1 && !bootDone}<span class="cursor">█</span>{/if}
        </div>
      {/each}
    </div>
  </div>
{/if}

<!-- Main dashboard -->
{#if !showSettings}
  <div class="layout" class:hidden={booting}>
    <Header brokerConnected={brokerConnected} onSettingsClick={openSettings} />

    <main class="dashboard">

      <!-- ── CLIMATE (BME280) ─────────────────────────────────────────── -->
      <SensorCard
        title={bme280.title}
        sensorId="bme280"
        connectivity={bme280.connectivity}
        lastSeen={bme280.lastSeen}
        stale={bme280.stale}
      >
        <div class="climate-layout">
          <TemperatureGauge value={tempC} />
          <div class="climate-readings">
            <ReadingRow
              label="TEMPERATURE"
              value={tempC != null ? tempC.toFixed(1) : '—.—'}
              unit="°C"
              status={tempStatus}
            />
            <ReadingRow
              label="HUMIDITY"
              value={humPct != null ? humPct.toFixed(0) : '——'}
              unit="%"
              status={humStatus}
            />
            <ReadingRow
              label="PRESSURE"
              value={presHpa != null ? presHpa.toFixed(0) : '————'}
              unit=" hPa"
              status={presStatus}
            />
          </div>
        </div>
      </SensorCard>

      <!-- ── AIR QUALITY (SCD40) ─────────────────────────────────────── -->
      <SensorCard
        title={scd40.title}
        sensorId="scd40"
        connectivity={scd40.connectivity}
        lastSeen={scd40.lastSeen}
        stale={scd40.stale}
      >
        <!-- CO₂ prominently with bar -->
        <div class="co2-block">
          <ReadingRow
            label="CO₂"
            value={co2Ppm != null ? co2Ppm.toFixed(0) : '————'}
            unit=" ppm"
            status={co2Status}
          />
          <BarMeter
            value={co2Ppm}
            min={400}
            max={2000}
            blocks={12}
            thresholds={THRESHOLDS.co2_ppm}
            label="CO₂ level bar"
          />
          <div class="co2-scale">
            <span class="dimmer">400</span>
            <span class="dimmer">GOOD</span>
            <span class="dimmer">WARN</span>
            <span class="dimmer">2000</span>
          </div>
        </div>

        <!-- Secondary: temperature + humidity from SCD40 -->
        {#if scdTempC != null || scdHumPct != null}
          <div class="air-secondary">
            {#if scdTempC != null}
              <ReadingRow
                label="TEMPERATURE"
                value={scdTempC.toFixed(1)}
                unit="°C"
                status={scdTempStatus}
              />
            {/if}
            {#if scdHumPct != null}
              <ReadingRow
                label="HUMIDITY"
                value={scdHumPct.toFixed(0)}
                unit="%"
                status={scdHumStatus}
              />
            {/if}
          </div>
        {:else}
          <p class="awaiting muted">AWAITING SENSOR DATA…</p>
        {/if}
      </SensorCard>

      <!-- ── AUDIO (INMP441) ────────────────────────────────────────── -->
      <SensorCard
        title={inmp441.title}
        sensorId="inmp441"
        connectivity={inmp441.connectivity}
        lastSeen={inmp441.lastSeen}
        stale={inmp441.stale}
      >
        <!-- WebSocket status badge -->
        <div class="ws-status">
          <span class="dot {wsConnected ? 'dot--online' : 'dot--unknown'}">●</span>
          <span class="label">{wsConnected ? 'STREAM LIVE' : 'STREAM IDLE'}</span>
        </div>

        <!-- Real-time EQ visualizer -->
        <EQVisualizer {getAudioFrame} connected={wsConnected} />

        <!-- Real-time waveform oscilloscope -->
        <WaveformScope {getAudioFrame} connected={wsConnected} />

        <!-- Summary RMS level from polled /sensors/inmp441 -->
        {#if inmp441.readings}
          {@const dbfs = inmp441.readings.db_level}
          <ReadingRow
            label="RMS (5s AVG)"
            value={dbfs.toFixed(1)}
            unit=" dBFS"
            status={statusFor(dbfs, THRESHOLDS.db_level)}
            sub={`~${dbfsToDB(dbfs).toFixed(1)} dB SPL`}
          />
        {:else}
          <ReadingRow label="RMS (5s AVG)" value="——" unit=" dBFS" status="unknown" sub="~—— dB SPL" />
        {/if}
      </SensorCard>
    </main>

    <StatusBar lastPoll={lastPoll} pollError={pollError} brokerConnected={brokerConnected} />
  </div>
{/if}

<style>
  /* Boot screen */
  .boot-screen {
    position: fixed; inset: 0;
    background: var(--bg);
    display: flex; align-items: center; justify-content: center;
    z-index: 7000;
  }
  .boot-lines { display: flex; flex-direction: column; gap: var(--u3); padding: var(--u8); }
  .boot-line  { font-family: var(--font-pixel); font-size: 10px; color: var(--primary); letter-spacing: 0.05em; white-space: pre; }
  .dim        { color: var(--dim); margin-right: var(--u2); }

  /* Layout */
  .layout { display: flex; flex-direction: column; min-height: 100vh; transition: opacity 0.3s; }
  .layout.hidden { opacity: 0; pointer-events: none; }

  /* Dashboard grid */
  .dashboard {
    flex: 1;
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: var(--u4);
    padding: var(--u5) var(--u6);
    align-items: start;
  }
  @media (max-width: 900px) { .dashboard { grid-template-columns: 1fr 1fr; } }
  @media (max-width: 580px) { .dashboard { grid-template-columns: 1fr; } }

  /* Climate panel layout */
  .climate-layout {
    display: flex;
    gap: var(--u5);
    align-items: flex-start;
  }
  .climate-readings {
    flex: 1;
    display: flex;
    flex-direction: column;
    gap: var(--u4);
  }

  /* CO₂ block */
  .co2-block {
    display: flex;
    flex-direction: column;
    gap: var(--u3);
    padding-bottom: var(--u4);
    border-bottom: 1px solid var(--dimmer);
  }
  .co2-scale {
    display: flex;
    justify-content: space-between;
    font-family: var(--font-pixel);
    font-size: 6px;
    color: var(--dimmer);
    margin-top: -2px;
  }
  .air-secondary {
    display: flex;
    flex-direction: column;
    gap: var(--u4);
    padding-top: var(--u2);
  }
  .awaiting {
    font-family: var(--font-pixel);
    font-size: 7px;
    padding-top: var(--u2);
  }

  /* WebSocket stream status */
  .ws-status {
    display: flex;
    align-items: center;
    gap: var(--u2);
    padding-bottom: var(--u3);
    border-bottom: 1px solid var(--dimmer);
  }
</style>
