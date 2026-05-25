<script>
  /**
   * ReadingRow — one labeled sensor reading with a color-coded LED indicator.
   *
   * Props:
   *   label   {string}  Reading name, e.g. "TEMPERATURE"
   *   value   {string}  Formatted value string, e.g. "22.4"
   *   unit    {string}  Unit suffix, e.g. "°C"
   *   status  {string}  "good" | "ok" | "warn" | "danger" | "unknown"
   *   sub     {string?} Optional second line (e.g. secondary value)
   */
  let { label = '', value = '—', unit = '', status = 'unknown', sub = '' } = $props();
</script>

<div class="reading-row">
  <div class="reading-label">
    <span class="indicator indicator--{status}" aria-label="Status: {status}"></span>
    <span class="label">{label}</span>
  </div>
  <div class="reading-values">
    <span class="reading-num reading--{status}">{value}<span class="reading-unit">{unit}</span></span>
    {#if sub}
      <span class="reading-sub muted">{sub}</span>
    {/if}
  </div>
</div>

<style>
  .reading-row {
    display: flex;
    flex-direction: column;
    gap: 3px;
  }

  .reading-label {
    display: flex;
    align-items: center;
    gap: var(--u2);
  }

  .reading-values {
    display: flex;
    align-items: baseline;
    gap: var(--u3);
    padding-left: calc(10px + var(--u2)); /* align under label, past indicator */
  }

  .reading-num {
    font-family: var(--font-vt);
    font-size: 42px;
    line-height: 1;
    transition: color 0.4s;
  }

  .reading-unit {
    font-family: var(--font-pixel);
    font-size: 8px;
    margin-left: 3px;
    vertical-align: middle;
    color: var(--dim);
  }

  .reading-sub {
    font-family: var(--font-vt);
    font-size: 20px;
    line-height: 1;
  }
</style>
