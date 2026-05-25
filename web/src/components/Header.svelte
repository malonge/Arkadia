<script>
  import { onMount } from 'svelte';
  import { LOCATION } from '../api.js';

  let { version = '1.1.0', brokerConnected = false, onSettingsClick } = $props();

  // Live clock — ticks every second
  let now = $state(new Date());

  onMount(() => {
    const id = setInterval(() => { now = new Date(); }, 1000);
    return () => clearInterval(id);
  });

  const timeStr = $derived(
    now.toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' })
  );
  const dateStr = $derived(
    now.toLocaleDateString('en-US', { weekday: 'short', year: 'numeric', month: 'short', day: '2-digit' })
      .toUpperCase()
  );
</script>

<header class="header pixel-border">
  <div class="header-left">
    <span class="logo glow">ARKADIA</span>
    <span class="version muted">v{version}</span>
  </div>

  <div class="header-center">
    <div class="clock-block">
      <span class="time glow">{timeStr}</span>
      <span class="date muted">{dateStr}</span>
    </div>
  </div>

  <div class="header-right">
    <div class="coords muted" title="Location">
      <span class="coords-label dimmer">◉</span>
      <span>{LOCATION.label}</span>
    </div>

    <div class="broker-status">
      <span
        class="dot {brokerConnected ? 'dot--online' : 'dot--offline'}"
        title={brokerConnected ? 'Broker connected' : 'Broker disconnected'}
        aria-label={brokerConnected ? 'Broker connected' : 'Broker disconnected'}
      >●</span>
      <span class="broker-label muted">{brokerConnected ? 'MQTT OK' : 'NO MQTT'}</span>
    </div>

    <button class="settings-btn" onclick={onSettingsClick} title="Settings" aria-label="Open settings">
      [⚙]
    </button>

    <span class="cursor">█</span>
  </div>
</header>

<style>
  .header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--u4);
    padding: var(--u3) var(--u6);
    background: var(--bg-card);
    flex-shrink: 0;
    flex-wrap: wrap;
    row-gap: var(--u2);
  }

  .header-left {
    display: flex;
    align-items: baseline;
    gap: var(--u4);
  }

  .logo {
    font-family: var(--font-pixel);
    font-size: 16px;
    letter-spacing: 0.15em;
  }

  .version {
    font-family: var(--font-pixel);
    font-size: 7px;
  }

  /* Clock */
  .header-center {
    flex: 1;
    display: flex;
    justify-content: center;
  }

  .clock-block {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 2px;
  }

  .time {
    font-family: var(--font-vt);
    font-size: 32px;
    line-height: 1;
    letter-spacing: 0.05em;
  }

  .date {
    font-family: var(--font-pixel);
    font-size: 7px;
    letter-spacing: 0.06em;
  }

  /* Right section */
  .header-right {
    display: flex;
    align-items: center;
    gap: var(--u4);
  }

  .coords {
    display: flex;
    align-items: center;
    gap: var(--u2);
    font-family: var(--font-pixel);
    font-size: 7px;
    letter-spacing: 0.04em;
  }

  .broker-status {
    display: flex;
    align-items: center;
    gap: var(--u2);
  }

  .dot {
    font-size: 14px;
  }

  .broker-label {
    font-family: var(--font-pixel);
    font-size: 7px;
  }

  .settings-btn {
    background: transparent;
    border: none;
    color: var(--dim);
    font-family: var(--font-pixel);
    font-size: 9px;
    cursor: pointer;
    padding: 2px var(--u2);
    transition: color 0.15s;
  }

  .settings-btn:hover {
    color: var(--primary);
    text-shadow: var(--glow);
  }

  .cursor {
    font-size: 14px;
    color: var(--accent);
  }
</style>
