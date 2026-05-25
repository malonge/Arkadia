<script>
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

  <span class="item">
    <span class="dimmer">ARKADIA v1.1.0</span>
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
