<script>
  /**
   * SensorCard — retro pixel-border panel for one sensor.
   *
   * Props:
   *   title        {string}  Panel heading (e.g. "CLIMATE")
   *   sensorId     {string}  Sensor ID for ARIA labels
   *   connectivity {string}  "online" | "offline" | "unknown"
   *   lastSeen     {string|null}  Human-readable last-seen string
   *   stale        {boolean} Whether the reading is stale
   */
  let {
    title = '',
    sensorId = '',
    connectivity = 'unknown',
    lastSeen = null,
    stale = false,
    children,
  } = $props();

  const dotClass = $derived(
    ({ online: 'dot--online', offline: 'dot--offline', unknown: 'dot--unknown' })[connectivity]
    ?? 'dot--unknown'
  );
</script>

<section
  class="card pixel-border {stale ? 'pixel-border--warning' : ''}"
  aria-label="{title} sensor panel"
>
  <!-- Card header strip -->
  <div class="card-header">
    <span class="card-title">{title}</span>
    <div class="card-status">
      {#if stale}
        <span class="badge badge--stale">STALE</span>
      {/if}
      <span class="dot {dotClass}" title="Connectivity: {connectivity}" aria-label="Connectivity: {connectivity}">●</span>
    </div>
  </div>

  <!-- Readings area — filled by parent via slot -->
  <div class="card-body">
    {@render children?.()}
  </div>

  <!-- Footer: last-seen timestamp -->
  <div class="card-footer">
    {#if lastSeen}
      <span class="last-seen muted">{lastSeen}</span>
    {:else}
      <span class="last-seen dimmer">AWAITING DATA…</span>
    {/if}
    <span class="sensor-id dimmer">{sensorId}</span>
  </div>
</section>

<style>
  .card {
    background: var(--bg-card);
    display: flex;
    flex-direction: column;
    min-height: 260px;
  }

  .card-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: var(--u3) var(--u4);
    border-bottom: 1px solid var(--dimmer);
    background: var(--bg-raised);
    flex-shrink: 0;
  }

  .card-title {
    font-family: var(--font-pixel);
    font-size: 9px;
    letter-spacing: 0.1em;
    color: var(--primary);
  }

  .card-status {
    display: flex;
    align-items: center;
    gap: var(--u3);
  }

  .card-body {
    flex: 1;
    padding: var(--u5) var(--u4);
    display: flex;
    flex-direction: column;
    gap: var(--u4);
  }

  .card-footer {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: var(--u2) var(--u4);
    border-top: 1px solid var(--dimmer);
    background: var(--bg-raised);
    flex-shrink: 0;
  }

  .last-seen, .sensor-id {
    font-family: var(--font-pixel);
    font-size: 7px;
  }
</style>
