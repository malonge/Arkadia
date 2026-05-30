<script>
  /**
   * EQVisualizer — 8-band retro equalizer drawn on a <canvas>.
   *
   * Each of the 8 ISO 266 octave bands is drawn as a column of discrete
   * pixel blocks.  The top block of each column is color-coded by amplitude
   * (green → lime → amber → red).  A peak-hold dot sits above the column and
   * decays at 18 dB/s after a 0.6 s hold period.
   *
   * When disconnected, bars pulse slowly with a sine wave idle animation.
   *
   * Props:
   *   getFrame   {() => object|null}  Function returning latest AudioStreamPayload
   *   connected  {boolean}            Whether the WebSocket is connected
   *   gain       {number}             dB boost added to each band before height
   *                                   mapping (default 30).  Does NOT affect the
   *                                   color thresholds, which stay anchored to
   *                                   actual amplitude.  Typical EQ bands for
   *                                   quiet room audio sit around -60 to -50 dBFS;
   *                                   gain=30 lifts those into the 50–75 % range.
   *                                   Raise if bars look flat; lower if they clip.
   */
  import { onMount } from 'svelte';

  let { getFrame = () => null, connected = false, gain = 30 } = $props();

  let container = $state(null);
  let canvas    = $state(null);

  // -- Constants -------------------------------------------------------------
  const BANDS       = 8;
  const BLOCKS      = 20;       // discrete height steps per bar
  const FLOOR_DB    = -80;      // level that maps to 0 blocks
  const GAP_PX      = 5;        // pixels between bars
  const PEAK_HOLD   = 0.6;      // seconds before decay starts
  const DECAY_RATE  = 18;       // dB per second decay

  const COLOR_BODY   = '#005c17';  // filled block body (--dimmer approx)
  const COLOR_EMPTY  = '#1e3a1e';  // empty block (--muted approx)
  const COLOR_STATUS = {
    good:    '#00ff41',
    ok:      '#aaff00',
    warn:    '#ffb000',
    danger:  '#ff3131',
    idle:    '#003a0e',
  };

  function levelToStatus(db) {
    if (db < -30) return 'good';
    if (db < -15) return 'ok';
    if (db < -6)  return 'warn';
    return 'danger';
  }

  function levelToBlocks(db) {
    // Apply gain (dB boost) for display height only.
    // Clamp so a very high gain never pushes past the top block.
    const boosted = Math.min(0, db + gain);
    const ratio   = Math.max(0, Math.min(1, (boosted - FLOOR_DB) / -FLOOR_DB));
    return Math.round(ratio * BLOCKS);
  }

  // -- Animation state (plain vars, not reactive) ----------------------------
  let peaks      = Array.from({ length: BANDS }, () => FLOOR_DB);
  let holdTimers = Array.from({ length: BANDS }, () => 0); // seconds since last peak update
  let animId     = null;
  let lastTime   = null;

  // -- Canvas drawing --------------------------------------------------------

  function drawFrame(ctx, w, h, frame, t, dt) {
    ctx.clearRect(0, 0, w, h);

    const blockH = Math.floor(h / BLOCKS);
    const totalGap = GAP_PX * (BANDS - 1);
    const barW = Math.max(4, Math.floor((w - totalGap) / BANDS));

    for (let i = 0; i < BANDS; i++) {
      const x = i * (barW + GAP_PX);

      let blocks, topStatus;

      if (connected && frame?.readings?.eq_bands?.levels_db) {
        const db = frame.readings.eq_bands.levels_db[i] ?? FLOOR_DB;
        blocks    = levelToBlocks(db);
        topStatus = levelToStatus(db);

        // Peak hold
        if (db > peaks[i]) {
          peaks[i]      = db;
          holdTimers[i] = 0;
        }
      } else {
        // Idle: gentle sine-wave pulse, offset per band
        const phase = (i / BANDS) * Math.PI * 2;
        const idleRatio = 0.08 + 0.04 * Math.sin(2 * Math.PI * 0.4 * t + phase);
        blocks    = Math.round(idleRatio * BLOCKS);
        topStatus = 'idle';
        peaks[i]  = FLOOR_DB; // reset peaks when disconnected
      }

      // -- Decay peaks -------------------------------------------------------
      holdTimers[i] += dt;
      if (holdTimers[i] > PEAK_HOLD) {
        peaks[i] -= DECAY_RATE * dt;
        peaks[i]  = Math.max(peaks[i], FLOOR_DB);
      }

      // -- Draw empty blocks -------------------------------------------------
      ctx.fillStyle = COLOR_EMPTY;
      for (let b = blocks; b < BLOCKS; b++) {
        const by = h - (b + 1) * blockH;
        ctx.fillRect(x, by + 1, barW, blockH - 2);
      }

      // -- Draw filled blocks (body, excluding the top cap) ------------------
      if (blocks > 1) {
        ctx.fillStyle = COLOR_BODY;
        ctx.fillRect(x, h - (blocks - 1) * blockH, barW, (blocks - 1) * blockH - 1);
      }

      // -- Draw top cap (colored by amplitude) -------------------------------
      if (blocks > 0) {
        const capColor = COLOR_STATUS[topStatus];
        ctx.fillStyle = capColor;
        ctx.shadowColor = capColor;
        ctx.shadowBlur  = topStatus !== 'idle' ? 6 : 0;
        ctx.fillRect(x, h - blocks * blockH, barW, blockH - 1);
        ctx.shadowBlur = 0;
      }

      // -- Draw peak-hold dot ------------------------------------------------
      if (connected && peaks[i] > FLOOR_DB + 1) {
        const peakBlocks = levelToBlocks(peaks[i]);
        if (peakBlocks > blocks) {
          const peakColor = COLOR_STATUS[levelToStatus(peaks[i])];
          ctx.fillStyle   = peakColor;
          ctx.shadowColor = peakColor;
          ctx.shadowBlur  = 8;
          const dotY = h - peakBlocks * blockH - 3;
          ctx.fillRect(x, dotY, barW, 2);
          ctx.shadowBlur = 0;
        }
      }
    }

    // -- Band labels ---------------------------------------------------------
    const LABELS = ['63', '125', '250', '500', '1k', '2k', '4k', '8k'];
    ctx.fillStyle = '#005c17';
    ctx.font = '7px monospace';
    ctx.textAlign = 'center';
    for (let i = 0; i < BANDS; i++) {
      const x = i * (barW + GAP_PX) + barW / 2;
      ctx.fillText(LABELS[i], x, h - 1);
    }
  }

  // -- rAF loop --------------------------------------------------------------

  $effect(() => {
    if (!canvas || !container) return;

    // Resize canvas to match container
    const ro = new ResizeObserver(([entry]) => {
      canvas.width  = Math.floor(entry.contentRect.width);
      canvas.height = 120;
    });
    ro.observe(container);

    // Animation loop
    let running = true;

    function loop(ts) {
      if (!running) return;

      const t  = ts / 1000;
      const dt = lastTime != null ? Math.min((ts - lastTime) / 1000, 0.1) : 0;
      lastTime = ts;

      const frame = getFrame();
      const ctx   = canvas.getContext('2d');
      if (ctx) drawFrame(ctx, canvas.width, canvas.height, frame, t, dt);

      animId = requestAnimationFrame(loop);
    }

    animId = requestAnimationFrame(loop);

    return () => {
      running = false;
      cancelAnimationFrame(animId);
      ro.disconnect();
    };
  });
</script>

<div bind:this={container} class="eq-container" aria-label="Equalizer visualization">
  <canvas bind:this={canvas} class="eq-canvas"></canvas>
</div>

<style>
  .eq-container {
    width: 100%;
    position: relative;
    border-bottom: 1px solid var(--dimmer);
    padding-bottom: var(--u2);
    margin-bottom: var(--u2);
  }

  .eq-canvas {
    display: block;
    width: 100%;
    height: 120px;
    image-rendering: pixelated;
  }
</style>
