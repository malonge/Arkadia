<script>
  /**
   * WaveformScope — oscilloscope-style waveform drawn on a <canvas>.
   *
   * The waveform array from the AudioStreamPayload is downsampled to fit the
   * canvas width.  Y positions are snapped to a pixel grid to give a chunky,
   * retro oscilloscope feel.  A phosphor glow is applied via ctx.shadowBlur.
   *
   * When disconnected, a flat idle line is shown with a slow pulse.
   *
   * Props:
   *   getFrame   {() => object|null}  Function returning latest AudioStreamPayload
   *   connected  {boolean}            Whether the WebSocket is connected
   *   gain       {number}             Y-axis amplification (default 8).
   *                                   Typical room audio sits at -30 to -40 dBFS
   *                                   (amplitude ≈ 0.01–0.03); gain=8 maps those
   *                                   signals to a clearly visible deflection.
   *                                   Values are clamped after amplification so
   *                                   loud signals never clip visually.
   */
  import { onMount } from 'svelte';

  let { getFrame = () => null, connected = false, gain = 8 } = $props();

  let container = $state(null);
  let canvas    = $state(null);

  const HEIGHT_PX  = 72;
  const GRID_SNAP  = 1;    // 1px snap — gain already provides the retro stepped look
  const GLOW_COLOR = '#00ff41';
  const IDLE_COLOR = '#003a0e';

  function snapY(y) {
    return Math.round(y / GRID_SNAP) * GRID_SNAP;
  }

  function drawFrame(ctx, w, h, frame, t) {
    ctx.clearRect(0, 0, w, h);

    const midY      = h / 2;
    const maxDefl   = midY - 2;   // leave 2px margin top and bottom

    if (connected && frame?.readings?.waveform?.length > 0) {
      const samples = frame.readings.waveform;

      // Helper: amplify, clamp, then snap to grid
      function sampleY(si) {
        const raw     = samples[Math.min(si, samples.length - 1)];
        const amp     = Math.max(-1, Math.min(1, raw * gain));
        return snapY(midY - amp * maxDefl);
      }

      // Draw with phosphor glow
      ctx.strokeStyle = GLOW_COLOR;
      ctx.shadowColor = GLOW_COLOR;
      ctx.shadowBlur  = 5;
      ctx.lineWidth   = 1.5;
      ctx.beginPath();

      for (let px = 0; px < w; px++) {
        const si = Math.floor(px * samples.length / w);
        const y  = sampleY(si);
        if (px === 0) ctx.moveTo(px, y);
        else          ctx.lineTo(px, y);
      }

      ctx.stroke();
      ctx.shadowBlur = 0;

      // Second pass: crisp bright line on top of glow
      ctx.strokeStyle = '#39ff14';
      ctx.lineWidth   = 1;
      ctx.beginPath();

      for (let px = 0; px < w; px++) {
        const si = Math.floor(px * samples.length / w);
        const y  = sampleY(si);
        if (px === 0) ctx.moveTo(px, y);
        else          ctx.lineTo(px, y);
      }
      ctx.stroke();

    } else {
      // Idle: slow flat line with faint pulse
      const pulse = 0.3 + 0.15 * Math.sin(2 * Math.PI * 0.6 * t);
      ctx.strokeStyle = IDLE_COLOR;
      ctx.globalAlpha = pulse;
      ctx.lineWidth   = 1.5;
      ctx.beginPath();
      ctx.moveTo(0, snapY(midY));
      ctx.lineTo(w, snapY(midY));
      ctx.stroke();
      ctx.globalAlpha = 1;
    }

    // Centre graticule line (very faint)
    ctx.strokeStyle = '#0a1a0a';
    ctx.lineWidth   = 1;
    ctx.setLineDash([4, 8]);
    ctx.beginPath();
    ctx.moveTo(0, midY);
    ctx.lineTo(w, midY);
    ctx.stroke();
    ctx.setLineDash([]);
  }

  let animId   = null;
  let lastTime = null;

  $effect(() => {
    if (!canvas || !container) return;

    const ro = new ResizeObserver(([entry]) => {
      // Half-resolution canvas for chunky pixel look, stretched by CSS
      canvas.width  = Math.floor(entry.contentRect.width / 2);
      canvas.height = HEIGHT_PX / 2;
    });
    ro.observe(container);

    let running = true;

    function loop(ts) {
      if (!running) return;
      const t = ts / 1000;

      const frame = getFrame();
      const ctx   = canvas.getContext('2d');
      if (ctx) drawFrame(ctx, canvas.width, canvas.height, frame, t);

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

<div bind:this={container} class="scope-container" aria-label="Waveform oscilloscope">
  <div class="scope-label label">WAVEFORM</div>
  <div class="scope-screen">
    <canvas bind:this={canvas} class="scope-canvas"></canvas>
  </div>
</div>

<style>
  .scope-container {
    display: flex;
    flex-direction: column;
    gap: var(--u2);
  }

  .scope-screen {
    background: var(--bg);
    border: 1px solid var(--dimmer);
    padding: 2px;
    box-shadow: inset 0 0 10px rgba(0, 255, 65, 0.05);
    overflow: hidden;
  }

  .scope-canvas {
    display: block;
    width: 100%;
    height: 72px;
    image-rendering: pixelated;
  }
</style>
