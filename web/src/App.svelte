<script>
  import { onMount } from 'svelte';
  import { getApiKey, dbfsToDB } from './api.js';
  import Header from './components/Header.svelte';
  import SensorCard from './components/SensorCard.svelte';
  import StatusBar from './components/StatusBar.svelte';
  import SettingsModal from './components/SettingsModal.svelte';
  import ReadingRow from './components/ReadingRow.svelte';

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
        <ReadingRow label="TEMPERATURE" value="—.—" unit="°C"  status="unknown" />
        <ReadingRow label="HUMIDITY"    value="——"  unit="%"    status="unknown" />
        <ReadingRow label="PRESSURE"    value="————" unit=" hPa" status="unknown" />
        <p class="coming-soon muted">LIVE DATA IN PR 10</p>
      </SensorCard>

      <!-- Air quality panel -->
      <SensorCard
        title={sensors.scd40.title}
        sensorId="scd40"
        connectivity={sensors.scd40.connectivity}
        lastSeen={sensors.scd40.lastSeen}
        stale={sensors.scd40.stale}
      >
        <ReadingRow label="CO₂"         value="————" unit=" ppm" status="unknown" />
        <ReadingRow label="TEMPERATURE" value="—.—"  unit="°C"  status="unknown" />
        <ReadingRow label="HUMIDITY"    value="——"   unit="%"    status="unknown" />
        <p class="coming-soon muted">LIVE DATA IN PR 10</p>
      </SensorCard>

      <!-- Audio panel -->
      <SensorCard
        title={sensors.inmp441.title}
        sensorId="inmp441"
        connectivity={sensors.inmp441.connectivity}
        lastSeen={sensors.inmp441.lastSeen}
        stale={sensors.inmp441.stale}
      >
        <!-- EQ bar placeholder with colored tops -->
        <div class="eq-placeholder" aria-label="Equalizer placeholder">
          {#each [
            { h: 6,  top: 'ok'     },
            { h: 10, top: 'good'   },
            { h: 8,  top: 'ok'     },
            { h: 14, top: 'warn'   },
            { h: 12, top: 'warn'   },
            { h: 9,  top: 'ok'     },
            { h: 5,  top: 'good'   },
            { h: 7,  top: 'ok'     },
          ] as bar}
            <div class="eq-col" style="height: {bar.h * 6}px">
              <div class="eq-top eq-top--{bar.top}"></div>
            </div>
          {/each}
        </div>

        <!-- Waveform oscilloscope placeholder -->
        <div class="waveform-placeholder" aria-label="Waveform oscilloscope placeholder">
          <span class="label">WAVEFORM</span>
          <div class="waveform-screen">
            <svg width="100%" height="48" preserveAspectRatio="none" aria-hidden="true">
              <!-- idle flat line with slight noise -->
              <polyline
                points="0,24 20,24 40,23 60,25 80,24 100,24 120,23 140,25 160,24 180,24 200,23 220,25 240,24 260,24 280,23 300,25 320,24"
                fill="none"
                stroke="var(--dimmer)"
                stroke-width="1.5"
              />
            </svg>
          </div>
        </div>

        <!-- Level readings: dBFS + estimated dB SPL -->
        <ReadingRow
          label="LEVEL"
          value="——"
          unit=" dBFS"
          status="unknown"
          sub="~—— dB SPL"
        />
        <p class="coming-soon muted">LIVE AUDIO IN PR 11</p>
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

  .coming-soon {
    font-family: var(--font-pixel);
    font-size: 7px;
    margin-top: var(--u2);
    padding-top: var(--u3);
    border-top: 1px solid var(--dimmer);
  }

  /* EQ bar placeholder */
  .eq-placeholder {
    display: flex;
    align-items: flex-end;
    gap: 4px;
    height: 90px;
    padding-bottom: 0;
    border-bottom: 1px solid var(--dimmer);
    margin-bottom: var(--u2);
  }

  .eq-col {
    flex: 1;
    min-width: 8px;
    background: var(--dim);
    position: relative;
    display: flex;
    flex-direction: column;
    justify-content: flex-start;
  }

  /* Top 3-pixel cap on each EQ bar — color indicates amplitude */
  .eq-top {
    height: 4px;
    width: 100%;
    flex-shrink: 0;
  }

  .eq-top--good   { background: var(--status-good);   box-shadow: 0 0 4px var(--status-good);   }
  .eq-top--ok     { background: var(--status-ok);     box-shadow: 0 0 4px var(--status-ok);     }
  .eq-top--warn   { background: var(--status-warn);   box-shadow: 0 0 4px var(--status-warn);   }
  .eq-top--danger { background: var(--status-danger); box-shadow: 0 0 4px var(--status-danger); }

  /* Waveform oscilloscope placeholder */
  .waveform-placeholder {
    display: flex;
    flex-direction: column;
    gap: var(--u2);
  }

  .waveform-screen {
    background: var(--bg);
    border: 1px solid var(--dimmer);
    padding: var(--u2);
    box-shadow: inset 0 0 8px rgba(0, 255, 65, 0.04);
  }
</style>
