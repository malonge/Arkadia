<script>
  import { setApiKey } from '../api.js';

  let { onSave } = $props();

  let input = $state('');
  let error = $state('');

  function save() {
    const key = input.trim();
    if (!key) {
      error = 'KEY CANNOT BE EMPTY';
      return;
    }
    setApiKey(key);
    onSave(key);
  }

  function handleKeydown(e) {
    if (e.key === 'Enter') save();
  }
</script>

<div class="overlay">
  <div class="modal pixel-border" role="dialog" aria-modal="true" aria-label="Enter API key">
    <div class="modal-header">
      <span class="glow">ARKADIA</span>
    </div>

    <div class="modal-body">
      <p class="prompt">ENTER API KEY TO CONTINUE</p>
      <p class="hint muted">Your key is stored only in this browser.</p>

      <!-- svelte-ignore a11y_autofocus -->
      <input
        class="key-input pixel-border"
        type="password"
        placeholder="••••••••••••••••"
        bind:value={input}
        onkeydown={handleKeydown}
        autofocus
        spellcheck="false"
        autocomplete="off"
      />

      {#if error}
        <p class="error danger">{error}</p>
      {/if}

      <button class="btn pixel-border" onclick={save}>
        [ CONNECT ]
      </button>
    </div>

    <div class="modal-footer muted">
      Set <code>MONITOR_API_KEY</code> in <code>/etc/home-monitor.env</code>
    </div>
  </div>
</div>

<style>
  .overlay {
    position: fixed;
    inset: 0;
    background: rgba(13, 2, 8, 0.95);
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 8000;
  }

  .modal {
    width: min(480px, 92vw);
    background: var(--bg-card);
    padding: var(--u6);
    display: flex;
    flex-direction: column;
    gap: var(--u5);
  }

  .modal-header {
    font-family: var(--font-pixel);
    font-size: 18px;
    text-align: center;
    letter-spacing: 0.1em;
    padding-bottom: var(--u4);
    border-bottom: 1px solid var(--dimmer);
  }

  .modal-body {
    display: flex;
    flex-direction: column;
    gap: var(--u4);
  }

  .prompt {
    font-family: var(--font-pixel);
    font-size: 9px;
    color: var(--primary);
    letter-spacing: 0.05em;
  }

  .hint {
    font-family: var(--font-pixel);
    font-size: 7px;
    line-height: 1.8;
  }

  .key-input {
    width: 100%;
    background: var(--bg);
    color: var(--primary);
    font-family: var(--font-vt);
    font-size: 24px;
    padding: var(--u3) var(--u4);
    outline: none;
    caret-color: var(--accent);
  }

  .key-input:focus {
    --border-color: var(--accent);
    box-shadow: var(--glow), var(--border-w) var(--border-w) 0 var(--dimmer);
  }

  .key-input::placeholder {
    color: var(--dimmer);
  }

  .error {
    font-family: var(--font-pixel);
    font-size: 8px;
  }

  .btn {
    align-self: flex-end;
    background: transparent;
    color: var(--primary);
    font-family: var(--font-pixel);
    font-size: 9px;
    padding: var(--u3) var(--u5);
    cursor: pointer;
    transition: background 0.1s;
    letter-spacing: 0.05em;
  }

  .btn:hover, .btn:focus {
    background: var(--muted);
    outline: none;
    text-shadow: var(--glow);
  }

  .modal-footer {
    font-family: var(--font-pixel);
    font-size: 7px;
    line-height: 2;
    padding-top: var(--u4);
    border-top: 1px solid var(--dimmer);
    text-align: center;
  }

  code {
    color: var(--accent);
    font-family: var(--font-vt);
    font-size: 16px;
  }
</style>
