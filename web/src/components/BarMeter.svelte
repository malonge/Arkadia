<script>
  /**
   * BarMeter — a horizontal row of discrete pixel blocks.
   *
   * The number of filled blocks is proportional to (value - min) / (max - min).
   * All filled blocks share the same color, determined by statusFor(value, thresholds).
   *
   * Props:
   *   value       {number|null}
   *   min         {number}       Default 0
   *   max         {number}       Default 100
   *   blocks      {number}       Number of discrete segments (default 12)
   *   thresholds  {Array}        statusFor-compatible range table (optional)
   *   label       {string}       Accessible label
   */
  import { statusFor } from '../api.js';

  let {
    value = null,
    min = 0,
    max = 100,
    blocks = 12,
    thresholds = null,
    label = 'Bar meter',
  } = $props();

  const STATUS_COLORS = {
    good:    'var(--status-good)',
    ok:      'var(--status-ok)',
    warn:    'var(--status-warn)',
    danger:  'var(--status-danger)',
    unknown: 'var(--dimmer)',
  };

  const filledCount = $derived.by(() => {
    if (value == null) return 0;
    const ratio = Math.max(0, Math.min(1, (value - min) / (max - min)));
    return Math.round(ratio * blocks);
  });

  const status = $derived(
    thresholds && value != null ? statusFor(value, thresholds) : 'unknown'
  );

  const fillColor = $derived(STATUS_COLORS[status] ?? STATUS_COLORS.unknown);
</script>

<div
  class="bar-meter"
  role="meter"
  aria-label={label}
  aria-valuenow={value ?? 0}
  aria-valuemin={min}
  aria-valuemax={max}
>
  {#each { length: blocks } as _, i}
    {@const filled = i < filledCount}
    <div
      class="segment {filled ? 'segment--filled' : 'segment--empty'}"
      style={filled ? `background: ${fillColor}; box-shadow: 0 0 3px ${fillColor};` : ''}
    ></div>
  {/each}
</div>

<style>
  .bar-meter {
    display: flex;
    gap: 3px;
    align-items: center;
    width: 100%;
  }

  .segment {
    flex: 1;
    height: 10px;
  }

  .segment--empty {
    background: var(--muted);
    border: 1px solid var(--dimmer);
  }

  .segment--filled {
    /* color applied via inline style */
  }
</style>
