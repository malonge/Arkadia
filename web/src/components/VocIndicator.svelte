<script>
  /**
   * VocIndicator — single large indicator for the SGP40 VOC Index.
   *
   * The VOC Index (1–500, Sensirion scale) is displayed as a prominent number
   * with a color-coded LED dot and a human-readable status label.
   *
   *   ≤ 100  : EXCELLENT  (green)
   *   101–150: GOOD       (lime)
   *   151–250: MODERATE   (amber)
   *   > 250  : POOR+      (red)
   *
   * Props:
   *   value   {number|null}  VOC Index, or null when no data
   *   status  {string}       "good" | "ok" | "warn" | "danger" | "unknown"
   */

  const LABELS = {
    good:    'EXCELLENT',
    ok:      'GOOD',
    warn:    'MODERATE',
    danger:  'POOR',
    unknown: 'NO DATA',
  };

  let { value = null, status = 'unknown' } = $props();

  const label = $derived(LABELS[status] ?? 'NO DATA');
</script>

<div class="voc-indicator" aria-label="VOC Index: {value ?? 'no data'}, status: {label}">
  <div class="voc-header">
    <span class="label">VOC INDEX</span>
    <span class="voc-label-tag label {status}">{label}</span>
  </div>

  <div class="voc-body">
    <!-- Large colored indicator dot -->
    <span class="voc-dot indicator indicator--{status}"></span>

    <!-- Prominent number -->
    <span class="voc-value reading--{status}">
      {value != null ? value : '———'}
    </span>

    <!-- Scale hint -->
    <span class="voc-scale dimmer">/ 500</span>
  </div>
</div>

<style>
  .voc-indicator {
    display: flex;
    flex-direction: column;
    gap: var(--u2);
    padding: var(--u3) 0;
    border-top: 1px solid var(--dimmer);
  }

  .voc-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
  }

  .voc-label-tag {
    letter-spacing: 0.06em;
  }

  /* Override label color to match status */
  .voc-label-tag.good    { color: var(--status-good);    }
  .voc-label-tag.ok      { color: var(--status-ok);      }
  .voc-label-tag.warn    { color: var(--status-warn);    }
  .voc-label-tag.danger  { color: var(--status-danger);  }
  .voc-label-tag.unknown { color: var(--dim);            }

  .voc-body {
    display: flex;
    align-items: center;
    gap: var(--u4);
  }

  /* Larger LED dot than the inline ReadingRow indicator */
  .voc-dot {
    width: 16px;
    height: 16px;
    flex-shrink: 0;
  }

  .voc-value {
    font-family: var(--font-vt);
    font-size: 52px;
    line-height: 1;
    transition: color 0.4s;
  }

  .voc-scale {
    font-family: var(--font-pixel);
    font-size: 7px;
    align-self: flex-end;
    padding-bottom: 6px;
  }
</style>
