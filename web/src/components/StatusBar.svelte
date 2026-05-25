<script>
  import { LOCATION } from '../api.js';
  let { lastPoll = null, pollError = false, brokerConnected = false } = $props();
</script>

<footer class="status-bar">
  <span class="item">
    <span class="dot {brokerConnected ? 'dot--online' : 'dot--offline'}">●</span>
    <span class="muted">{brokerConnected ? 'BROKER OK' : 'BROKER OFFLINE'}</span>
  </span>

  <span class="item">
    {#if pollError}
      <span class="danger">▲ API ERROR</span>
    {:else if lastPoll}
      <span class="muted">LAST POLL: {lastPoll}</span>
    {:else}
      <span class="dimmer">POLLING…</span>
    {/if}
  </span>

  <span class="item coords">
    <span class="dimmer">◉</span>
    <span class="muted">{LOCATION.label}</span>
  </span>
</footer>

<style>
  .status-bar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--u4);
    padding: var(--u2) var(--u6);
    border-top: 1px solid var(--dimmer);
    background: var(--bg-card);
    flex-shrink: 0;
    flex-wrap: wrap;
  }

  .item {
    display: flex;
    align-items: center;
    gap: var(--u2);
    font-family: var(--font-pixel);
    font-size: 7px;
  }

  .dot {
    font-size: 10px;
  }
</style>
