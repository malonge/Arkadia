<script>
  /**
   * TemperatureGauge — vertical column of 16 discrete pixel blocks.
   *
   * Blocks fill from the bottom up as temperature increases.
   * Each block is colored by its own temperature midpoint, so the column
   * shows a visible blue→teal→green→amber→red gradient as the gauge fills.
   *
   * Props:
   *   value   {number|null}  Current temperature in °C
   *   min     {number}       Gauge minimum (default 0 °C)
   *   max     {number}       Gauge maximum (default 40 °C)
   *   blocks  {number}       Number of discrete steps (default 16)
   */
  let { value = null, min = 0, max = 40, blocks = 16 } = $props();

  // Color stops keyed by the upper boundary of each temperature zone.
  const COLOR_STOPS = [
    { below: 10, color: '#0088ff' },  // blue   — cold
    { below: 16, color: '#00ccbb' },  // teal   — cool
    { below: 26, color: '#00ff41' },  // green  — comfortable
    { below: 30, color: '#ffb000' },  // amber  — warm
    { below: Infinity, color: '#ff3131' }, // red — hot
  ];

  function colorFor(tempC) {
    for (const { below, color } of COLOR_STOPS) {
      if (tempC < below) return color;
    }
    return '#ff3131';
  }

  /**
   * Build the block array, bottom-first (index 0 = coldest block).
   * CSS uses flex-direction: column-reverse to render bottom-first visually.
   */
  const blockData = $derived.by(() => {
    const arr = [];
    const range = max - min;
    for (let i = 0; i < blocks; i++) {
      const blockLo  = min + (i / blocks) * range;
      const blockHi  = min + ((i + 1) / blocks) * range;
      const blockMid = (blockLo + blockHi) / 2;
      const filled   = value != null && value >= blockLo;
      arr.push({ filled, color: colorFor(blockMid) });
    }
    return arr;
  });

  // Formatted temperature label
  const label = $derived(value != null ? `${value.toFixed(1)}°` : '—°');
</script>

<div class="gauge" aria-label="Temperature gauge: {label}" role="img">
  <div class="blocks">
    {#each blockData as blk}
      <div
        class="block {blk.filled ? 'block--filled' : 'block--empty'}"
        style={blk.filled ? `background:${blk.color}; box-shadow: 0 0 4px ${blk.color}88;` : ''}
      ></div>
    {/each}
  </div>
  <span class="gauge-label">{label}</span>
</div>

<style>
  .gauge {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: var(--u2);
    flex-shrink: 0;
  }

  .blocks {
    display: flex;
    flex-direction: column-reverse; /* index 0 renders at bottom */
    gap: 3px;
    width: 18px;
  }

  .block {
    width: 18px;
    height: 7px;
    flex-shrink: 0;
  }

  .block--empty {
    background: var(--muted);
    border: 1px solid var(--dimmer);
  }

  .block--filled {
    /* color and box-shadow set via inline style */
  }

  .gauge-label {
    font-family: var(--font-pixel);
    font-size: 6px;
    color: var(--dim);
    text-align: center;
    line-height: 1;
  }
</style>
