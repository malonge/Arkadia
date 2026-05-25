<script>
  import { onMount } from 'svelte';
  import { getApiKey } from './api.js';
  import Header from './components/Header.svelte';
  import SensorCard from './components/SensorCard.svelte';
  import StatusBar from './components/StatusBar.svelte';
  import SettingsModal from './components/SettingsModal.svelte';

  // ---------------------------------------------------------------------------
  // Settings gate
  // ---------------------------------------------------------------------------
  let apiKey = $state(getApiKey());
  let showSettings = $state(!getApiKey());

  function handleSave(key) {
    apiKey = key;
    showSettings = false;
    // Re-trigger boot when key is set for the first time
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

  let booting = $state(true);
  let bootLines = $state([]);
  let bootDone = $state(false);

  function startBoot() {
    booting = true;
    bootLines = [];
    bootDone = false;

    let lineIdx = 0;
    let charIdx = 0;
    let current = '';

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
        lineIdx++;
        charIdx = 0;
        current = '';
        setTimeout(tick, lineIdx === BOOT_LINES.length ? 400 : 80);
      }
    }

    tick();
  }

  // ---------------------------------------------------------------------------
  // Placeholder sensor state (data wired in PR 10/11)
  // ---------------------------------------------------------------------------
  // These will be replaced by real API polling in subsequent PRs.
  const sensors = {
    bme280:  { title: 'CLIMATE',     connectivity: 'unknown', lastSeen: null, stale: false },
    scd40:   { title: 'AIR QUALITY', connectivity: 'unknown', lastSeen: null, stale: false },
    inmp441: { title: 'AUDIO',       connectivity: 'unknown', lastSeen: null, stale: false },
  };

  let brokerConnected = $state(false);
  let lastPoll = $state(null);
  let pollError = $state(false);

  // ---------------------------------------------------------------------------
  // Lifecycle
  // ---------------------------------------------------------------------------
  onMount(() => {
    if (apiKey) startBoot();
  });
</script>

<!-- Settings modal blocks everything until key is entered -->
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

<!-- Main dashboard (rendered behind boot overlay for instant display after fade) -->
{#if !showSettings}
  <div class="layout" class:hidden={booting}>
    <Header
      brokerConnected={brokerConnected}
      onSettingsClick={openSettings}
    />

    <main class="dashboard">
      <!-- Climate panel -->
      <SensorCard
        title={sensors.bme280.title}
        sensorId="bme280"
        connectivity={sensors.bme280.connectivity}
        lastSeen={sensors.bme280.lastSeen}
        stale={sensors.bme280.stale}
      >
        <div class="placeholder-body">
          <p class="label">TEMPERATURE</p>
          <p class="value dimmer">—.— °C</p>
          <p class="label">HUMIDITY</p>
          <p class="value dimmer">—— %</p>
          <p class="label">PRESSURE</p>
          <p class="value dimmer">———— hPa</p>
          <p class="coming-soon muted">LIVE DATA IN PR 10</p>
        </div>
      </SensorCard>

      <!-- Air quality panel -->
      <SensorCard
        title={sensors.scd40.title}
        sensorId="scd40"
        connectivity={sensors.scd40.connectivity}
        lastSeen={sensors.scd40.lastSeen}
        stale={sensors.scd40.stale}
      >
        <div class="placeholder-body">
          <p class="label">CO₂</p>
          <p class="value dimmer">———— ppm</p>
          <p class="label">TEMPERATURE</p>
          <p class="value dimmer">—.— °C</p>
          <p class="label">HUMIDITY</p>
          <p class="value dimmer">—— %</p>
          <p class="coming-soon muted">LIVE DATA IN PR 10</p>
        </div>
      </SensorCard>

      <!-- Audio panel -->
      <SensorCard
        title={sensors.inmp441.title}
        sensorId="inmp441"
        connectivity={sensors.inmp441.connectivity}
        lastSeen={sensors.inmp441.lastSeen}
        stale={sensors.inmp441.stale}
      >
        <div class="placeholder-body">
          <!-- EQ bar placeholder -->
          <div class="eq-placeholder" aria-hidden="true">
            {#each [6, 10, 8, 14, 12, 9, 5, 7] as h}
              <div class="eq-col" style="height: {h * 6}px"></div>
            {/each}
          </div>
          <p class="label">RMS LEVEL</p>
          <p class="value dimmer">—— dBFS</p>
          <p class="coming-soon muted">LIVE AUDIO IN PR 11</p>
        </div>
      </SensorCard>
    </main>

    <StatusBar
      lastPoll={lastPoll}
      pollError={pollError}
      brokerConnected={brokerConnected}
    />
  </div>
{/if}

<style>
  /* Boot screen */
  .boot-screen {
    position: fixed;
    inset: 0;
    background: var(--bg);
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 7000;
  }

  .boot-lines {
    display: flex;
    flex-direction: column;
    gap: var(--u3);
    padding: var(--u8);
  }

  .boot-line {
    font-family: var(--font-pixel);
    font-size: 10px;
    color: var(--primary);
    letter-spacing: 0.05em;
    white-space: pre;
  }

  .dim {
    color: var(--dim);
    margin-right: var(--u2);
  }

  /* Main layout */
  .layout {
    display: flex;
    flex-direction: column;
    min-height: 100vh;
    transition: opacity 0.3s;
  }

  .layout.hidden {
    opacity: 0;
    pointer-events: none;
  }

  /* Dashboard grid */
  .dashboard {
    flex: 1;
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: var(--u4);
    padding: var(--u5) var(--u6);
    align-items: start;
  }

  @media (max-width: 900px) {
    .dashboard {
      grid-template-columns: 1fr 1fr;
    }
  }

  @media (max-width: 580px) {
    .dashboard {
      grid-template-columns: 1fr;
    }
  }

  /* Placeholder content inside cards */
  .placeholder-body {
    display: flex;
    flex-direction: column;
    gap: var(--u3);
  }

  .value {
    font-family: var(--font-vt);
    font-size: 40px;
    line-height: 1;
  }

  .coming-soon {
    font-family: var(--font-pixel);
    font-size: 7px;
    margin-top: var(--u3);
    padding-top: var(--u3);
    border-top: 1px solid var(--dimmer);
  }

  /* Static EQ bar placeholder */
  .eq-placeholder {
    display: flex;
    align-items: flex-end;
    gap: 4px;
    height: 90px;
    padding-bottom: var(--u2);
    border-bottom: 1px solid var(--dimmer);
  }

  .eq-col {
    flex: 1;
    background: var(--dimmer);
    min-width: 8px;
  }
</style>
