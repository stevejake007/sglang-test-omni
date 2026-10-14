// Server command generator for Qwen3-Omni deployment docs.
// Mounts into #sgl-server-gen-mount when the page contains that element.
//
// Visual design: one card row per dimension, pill-style radio buttons.
// Brand style: SGLang docs.sglang.io design system — primary #d55816,
// warm white #fffcfb / deep charcoal #1d1d1d, Inter, 12px rounded cards,
// grid-decoration page background (see _static/css/custom_log.css).
//
// Architecture: each dimension defines an independent contribute(ctx) function
// returning { prefix?, flags?, config?, modelPath?, extraArgs? }. buildCommand() assembles them.
// extraArgs are appended without '--' prefix (dotted-path sglang-omni passthrough).
// To add a new option: add one entry to the relevant dimension object.
(function () {
  'use strict';

  // ─── Dimension definitions ────────────────────────────────────────────────

  var MODES = {
    'text-only': {
      label:    'Thinker-only',
      subtitle: 'text out only',
      audio:    'Text output only',
      gpus:     function()    { return '1 GPU'; },
      contribute: function()  { return { flags: ['--text-only'] }; },
    },
    'speech': {
      label:    'Thinker-Talker',
      subtitle: 'audio capable',
      audio:    'Text + Audio capable',
      gpus:     function(ctx) { return TOPOLOGIES[ctx.topo].gpus(ctx); },
      contribute: function()  { return {}; },
    },
  };

  // Hardware is a sub-dimension of colocated topology (BF16 only).
  // Each entry maps to a YAML memory budget profile calibrated for that GPU.
  var HARDWARE = {
    'h20': {
      label:       'H20',
      subtitle:    '≥ 96 GB',
      config_bf16: 'examples/configs/qwen3_omni_colocated_h20.yaml',
    },
    'h200': {
      label:       'H200',
      subtitle:    '≥ 141 GB',
      config_bf16: 'examples/configs/qwen3_omni_colocated_h200.yaml',
    },
  };

  var TOPOLOGIES = {
    'disaggregated': {
      label:    'Disaggregated',
      subtitle: 'default',
      gpus:     function(ctx) { return THINKER_TP[ctx.tp].gpus(); },
      contribute: function(ctx) { return THINKER_TP[ctx.tp].contribute(); },
    },
    'colocated': {
      label:    'Colocated',
      subtitle: 'single high-VRAM GPU',
      gpus:     function()    { return '1 GPU (H20 / H200)'; },
      contribute: function(ctx)  {
        return {
          flags:  ['--colocate'],
          config: HARDWARE[ctx.hw].config_bf16,
        };
      },
    },
  };

  // Thinker TP is a sub-dimension of disaggregated topology.
  // Disabled when mode=text-only or topo=colocated.
  var THINKER_TP = {
    'tp1': {
      label:    'TP=1',
      subtitle: 'default',
      gpus:     function() { return '2 GPUs'; },
      contribute: function() { return {}; },
    },
    'tp2': {
      label:    'TP=2',
      subtitle: '3 GPUs',
      gpus:     function() { return '3 GPUs'; },
      contribute: function() {
        return { flags: ['--thinker.tp_size 2', '--thinker.gpu "[0, 1]"', '--talker_ar.gpu 2'] };
      },
    },
  };

  // Precision: BF16 is the default (no extra args).
  // FP8 always uses the native FP8 checkpoint — quantization is inferred automatically
  // by the thinker/talker workers from the checkpoint config, so no server-side flag needed.
  // Colocated FP8 additionally switches to a dedicated YAML for the memory budget.
  // INT4 uses the AutoRound checkpoint. For speech, the thinker is INT4 while
  // talker/code2wav load as BF16 from the same checkpoint.
  var PRECISIONS = {
    'bf16': {
      label:    'BF16',
      subtitle: 'default',
      contribute: function() { return {}; },
    },
    'fp8': {
      label:    'FP8',
      subtitle: '',
      contribute: function(ctx) {
        if (ctx.mode === 'speech' && ctx.topo === 'colocated') {
          return {
            config:    'examples/configs/qwen3_omni_fp8_colocated.yaml',
            modelPath: 'marksverdhei/Qwen3-Omni-30B-A3B-FP8',
          };
        }
        return { modelPath: 'marksverdhei/Qwen3-Omni-30B-A3B-FP8' };
      },
    },
    'int4': {
      label:    'INT4 thinker',
      subtitle: 'AutoRound',
      contribute: function() {
        return { modelPath: 'Intel/Qwen3-Omni-30B-A3B-Instruct-int4-AutoRound' };
      },
    },
  };

  // ─── Key flag explanations ────────────────────────────────────────────────
  // Returns [{flag, desc}] for non-default flags in the current combination.
  function getExplanations(ctx) {
    var items = [];
    if (ctx.mode === 'text-only') {
      items.push({ flag: '--text-only', desc: 'Thinker-only pipeline — no talker, no audio output' });
    } else {
      if (ctx.topo === 'colocated') {
        items.push({ flag: '--colocate', desc: 'All GPU stages share a single high-VRAM GPU' });
        if (ctx.prec === 'fp8') {
          items.push({ flag: '--config …fp8_colocated.yaml', desc: 'FP8 memory budget profile; sets model path to marksverdhei/Qwen3-Omni-30B-A3B-FP8' });
        } else {
          var hwDef = HARDWARE[ctx.hw];
          items.push({ flag: '--config …colocated_' + ctx.hw + '.yaml', desc: 'Memory budget profile calibrated for ' + hwDef.label + ' (' + hwDef.subtitle + ')' });
        }
      } else if (ctx.tp === 'tp2') {
        items.push({ flag: '--thinker.tp_size 2', desc: 'Tensor-parallel the thinker across 2 GPUs' });
        items.push({ flag: '--thinker.gpu "[0, 1]"',  desc: 'Assign thinker TP ranks to GPU 0 and GPU 1' });
        items.push({ flag: '--talker_ar.gpu 2',       desc: 'Assign talker to GPU 2' });
      }
    }
    if (ctx.prec === 'fp8' && !(ctx.mode === 'speech' && ctx.topo === 'colocated')) {
      var fp8Desc = 'Native FP8 checkpoint; quantization inferred automatically for both thinker and talker AR stages';
      items.push({ flag: '--model-path marksverdhei/…FP8', desc: fp8Desc });
    }
    if (ctx.prec === 'int4') {
      var int4Desc = ctx.mode === 'speech'
        ? 'AutoRound INT4 thinker checkpoint; talker/code2wav load as BF16'
        : 'AutoRound INT4 thinker checkpoint';
      items.push({ flag: '--model-path Intel/…int4-AutoRound', desc: int4Desc });
    }
    if (items.length === 0) {
      items.push({ flag: '(no extra flags)', desc: 'Disaggregated speech pipeline: thinker and code2wav on GPU 0, talker alone on GPU 1 by default' });
    }
    return items;
  }

  // ─── Recommended hardware ─────────────────────────────────────────────────
  // Only colocated BF16 has an explicit hardware calibration profile in the repo
  // (qwen3_omni_colocated_h20.yaml: "single-H20 calibration profile").
  // All other combinations return null — GPU count badge already conveys
  // the key constraint; guessing GPU models would be misleading.
  function getHardware(ctx) {
    if (ctx.mode === 'speech' && ctx.topo === 'colocated') {
      var hwDef = HARDWARE[ctx.hw];
      return hwDef.label + ' (' + hwDef.subtitle + ')';
    }
    return null;
  }

  // ─── Command builder ──────────────────────────────────────────────────────
  function buildCommand(ctx) {
    var modeDef  = MODES[ctx.mode];
    var isSpeech = ctx.mode === 'speech';
    var topoDef  = isSpeech ? TOPOLOGIES[ctx.topo] : null;
    var precDef  = PRECISIONS[ctx.prec];

    var mc = modeDef.contribute(ctx);
    var tc = topoDef ? topoDef.contribute(ctx) : {};
    var pc = precDef.contribute(ctx);

    var prefix     = tc.prefix || mc.prefix || '';
    var flags      = (mc.flags || []).concat(tc.flags || []);
    var configFile = pc.config || tc.config || mc.config || null;
    var modelPath  = pc.modelPath || 'Qwen/Qwen3-Omni-30B-A3B-Instruct';
    var extraArgs  = pc.extraArgs || [];

    var parts = ['--model-path ' + modelPath];
    for (var i = 0; i < flags.length; i++) parts.push(flags[i]);
    if (configFile) parts.push('--config ' + configFile);
    parts.push('--port 8008');
    for (var k = 0; k < extraArgs.length; k++) parts.push(extraArgs[k]);

    var cmd = (prefix ? prefix + ' ' : '') + 'sgl-omni serve';
    for (var j = 0; j < parts.length; j++) cmd += ' \\\n  ' + parts[j];
    return cmd;
  }

  // ─── Clipboard fallback (works without HTTPS / clipboard permission) ─────
  function fallbackCopy(text, done) {
    var ta = document.createElement('textarea');
    ta.value = text;
    ta.style.cssText = 'position:fixed;top:0;left:0;opacity:0;';
    document.body.appendChild(ta);
    ta.focus();
    ta.select();
    try { document.execCommand('copy'); done(); } catch (e) {}
    document.body.removeChild(ta);
  }

  // ─── Dark mode detection ──────────────────────────────────────────────────
  function detectDark() {
    var html = document.documentElement;
    return html.classList.contains('dark') ||
           html.getAttribute('data-theme') === 'dark' ||
           html.getAttribute('data-color-mode') === 'dark';
  }

  // ─── Renderer ─────────────────────────────────────────────────────────────
  function render(mountEl) {
    var state = { mode: 'text-only', topo: 'disaggregated', prec: 'bf16', tp: 'tp1', hw: 'h20' };
    var dark  = detectDark();

    function update() {
      dark = detectDark();

      // ── SGLang brand tokens (docs.sglang.io design system) ──
      var ACCENT     = '#d55816';                      // brand orange
      var ACCENT_DEEP = dark ? '#f5b693' : '#a8470f';  // readable orange text
      var cardBg     = dark ? '#262628' : '#ffffff';
      var cardBorder = dark ? 'rgba(255,255,255,0.10)' : '#eee6df';
      var titleColor = ACCENT_DEEP;
      var btnBg      = dark ? '#2f2f31' : '#ffffff';
      var btnBorder  = dark ? 'rgba(255,255,255,0.22)' : '#e2d6cc';
      var btnColor   = dark ? '#e5e7eb' : '#4b4b4b';
      var cmdBg      = dark ? '#101012' : '#fff7f1';
      var cmdColor   = dark ? '#e5e7eb' : '#374151';
      var cardShadow = 'box-shadow:0 1px 2px rgba(29,29,29,0.04),0 4px 14px rgba(213,88,22,0.07);';

      var containerS = 'max-width:900px;display:flex;flex-direction:column;gap:8px;'
                     + 'font-family:Inter,"PingFang SC","Microsoft YaHei",system-ui,-apple-system,sans-serif;';

      var cardS = 'padding:10px 14px;'
                + 'border:1px solid ' + cardBorder + ';'
                + 'border-left:3px solid ' + ACCENT + ';'
                + 'border-radius:12px;'
                + 'display:flex;align-items:center;gap:12px;'
                + 'background:' + cardBg + ';'
                + cardShadow;

      var titleS = 'font-size:13px;font-weight:600;min-width:150px;flex-shrink:0;color:' + titleColor + ';';
      var itemsS = 'display:flex;row-gap:6px;column-gap:8px;flex-wrap:wrap;align-items:center;';
      var subS   = 'display:block;font-size:10px;margin-top:2px;line-height:1.15;opacity:0.75;';

      function btnS(active) {
        return 'padding:6px 14px;'
             + 'border:1px solid ' + (active ? ACCENT : btnBorder) + ';'
             + 'border-radius:999px;cursor:pointer;'
             + 'display:inline-flex;flex-direction:column;align-items:center;justify-content:center;'
             + 'font-weight:600;font-size:13px;user-select:none;'
             + 'min-width:64px;text-align:center;'
             + 'background:' + (active ? ACCENT : btnBg) + ';'
             + 'color:' + (active ? '#fff' : btnColor) + ';'
             + 'box-shadow:' + (active ? '0 2px 10px rgba(213,88,22,0.28)' : 'none') + ';';
      }

      function makeRow(title, items, activeId) {
        var btns = items.map(function(it) {
          var isDisabled = !!it.disabled;
          var isActive   = it.id === activeId && (!isDisabled || !!it.locked);
          var sub  = it.subtitle ? '<small style="' + subS + '">' + it.subtitle + '</small>' : '';
          var extra = isDisabled ? 'opacity:0.4;cursor:not-allowed;' : '';
          return '<button class="sgl-gen-btn" data-dim="' + it.dim + '" data-val="' + it.id + '" '
               + (isDisabled ? 'data-disabled="1" ' : '')
               + 'style="' + btnS(isActive) + extra + '">'
               + it.label + sub + '</button>';
        }).join('');
        return '<div style="' + cardS + '">'
             + '<div style="' + titleS + '">' + title + '</div>'
             + '<div style="' + itemsS + '">' + btns + '</div>'
             + '</div>';
      }

      var ctx      = state;
      var modeDef  = MODES[ctx.mode];
      var isSpeech = ctx.mode === 'speech';

      // ── Mode row ──
      var modeItems = Object.keys(MODES).map(function(k) {
        return { id: k, dim: 'mode', label: MODES[k].label, subtitle: MODES[k].subtitle };
      });
      var html = makeRow('Mode', modeItems, ctx.mode);

      // ── Topology row (disabled/N/A when text-only) ──
      var topoItems = Object.keys(TOPOLOGIES).map(function(k) {
        return { id: k, dim: 'topo', label: TOPOLOGIES[k].label, subtitle: TOPOLOGIES[k].subtitle,
                 disabled: !isSpeech, locked: false };
      });
      html += makeRow('Topology', topoItems, ctx.topo);

      // ── Thinker TP row (N/A when text-only; locked to TP=1 when colocated) ──
      var tpDisabled = !isSpeech || ctx.topo === 'colocated';
      var tpLocked   = isSpeech && ctx.topo === 'colocated';
      var tpItems = Object.keys(THINKER_TP).map(function(k) {
        return { id: k, dim: 'tp', label: THINKER_TP[k].label, subtitle: THINKER_TP[k].subtitle,
                 disabled: tpDisabled, locked: tpLocked };
      });
      html += makeRow('Thinker TP', tpItems, ctx.tp);

      // ── Precision row ──
      var precItems = Object.keys(PRECISIONS).map(function(k) {
        return { id: k, dim: 'prec', label: PRECISIONS[k].label, subtitle: PRECISIONS[k].subtitle };
      });
      html += makeRow('Precision', precItems, ctx.prec);

      // ── Hardware row (colocated BF16 only — selects per-GPU memory budget YAML) ──
      if (isSpeech && ctx.topo === 'colocated' && ctx.prec === 'bf16') {
        var hwItems = Object.keys(HARDWARE).map(function(k) {
          return { id: k, dim: 'hw', label: HARDWARE[k].label, subtitle: HARDWARE[k].subtitle };
        });
        html += makeRow('Hardware', hwItems, ctx.hw);
      }

      // ── Info badges (brand palette) ──
      function badge(bg, fg, text) {
        return '<span style="padding:3px 12px;border-radius:999px;font-size:0.8em;'
             + 'font-weight:600;background:' + bg + ';color:' + fg + ';white-space:nowrap;'
             + 'border:1px solid rgba(213,88,22,0.15);">'
             + text + '</span>';
      }
      var hw = getHardware(ctx);
      html += '<div style="' + cardS + 'gap:8px;flex-wrap:wrap;">'
            + badge('#fdeee4', '#a8470f', '&#128421;&#xFE0E; ' + modeDef.gpus(ctx))
            + badge('#f2efe9', '#555c66', '&#128266;&#xFE0E; ' + modeDef.audio)
            + (hw ? badge('#d55816', '#ffffff', '&#128187;&#xFE0E; ' + hw) : '')
            + '</div>';

      // ── Command row ──
      var cmdPreS  = 'flex:1;padding:14px 18px;background:' + cmdBg + ';border-radius:12px;'
                   + 'font-family:Menlo,Monaco,"Courier New",monospace;'
                   + 'font-size:12px;line-height:1.7;color:' + cmdColor + ';'
                   + 'white-space:pre;overflow-x:auto;margin:0;border:1px solid ' + cardBorder + ';';
      var copyBtnS = 'padding:6px 14px;font-size:11px;width:72px;text-align:center;'
                   + 'background:' + ACCENT + ';color:#fff;'
                   + 'border:1px solid ' + ACCENT + ';border-radius:999px;cursor:pointer;flex-shrink:0;'
                   + 'font-weight:600;';
      html += '<div style="' + cardS + '">'
            + '<div style="' + titleS + '">Run this Command:</div>'
            + '<pre id="sgl-cmd" style="' + cmdPreS + '">' + buildCommand(ctx) + '</pre>'
            + '<button id="sgl-cmd-copy" style="' + copyBtnS + '">Copy</button>'
            + '</div>';

      // ── Key flags ──
      var explanations = getExplanations(ctx);
      var flagRowS = 'display:flex;flex-direction:column;gap:6px;flex:1;';
      var flagLineS = 'display:flex;gap:12px;align-items:baseline;font-size:12px;';
      var flagNameS = 'font-family:Menlo,Monaco,"Courier New",monospace;'
                    + 'color:' + ACCENT_DEEP + ';'
                    + 'white-space:nowrap;flex-shrink:0;min-width:220px;';
      var flagDescS = 'color:' + (dark ? '#d8d8d8' : '#4b4b4b') + ';opacity:0.9;';
      var lines = explanations.map(function(e) {
        return '<div style="' + flagLineS + '">'
             + '<span style="' + flagNameS + '">' + e.flag + '</span>'
             + '<span style="' + flagDescS + '">' + e.desc + '</span>'
             + '</div>';
      }).join('');
      html += '<div style="' + cardS + 'align-items:flex-start;">'
            + '<div style="' + titleS + '">Key flags:</div>'
            + '<div style="' + flagRowS + '">' + lines + '</div>'
            + '</div>';

      mountEl.innerHTML = '<div style="' + containerS + '">' + html + '</div>';

      mountEl.querySelectorAll('button[data-dim]').forEach(function(btn) {
        btn.addEventListener('click', function() {
          if (btn.getAttribute('data-disabled')) return;
          var dim = btn.getAttribute('data-dim');
          var val = btn.getAttribute('data-val');
          state[dim] = val;
          if (dim === 'mode' && val === 'text-only') {
            state.topo = 'disaggregated';
            state.tp   = 'tp1';
          }
          if (dim === 'topo' && val === 'colocated') {
            state.tp = 'tp1';
          }
          update();
        });
      });

      var copyBtn = document.getElementById('sgl-cmd-copy');
      if (copyBtn) {
        copyBtn.addEventListener('click', function() {
          var text = document.getElementById('sgl-cmd').textContent;
          var flash = function() {
            copyBtn.textContent = 'Copied!';
            setTimeout(function() { copyBtn.textContent = 'Copy'; }, 1500);
          };
          if (navigator.clipboard && navigator.clipboard.writeText) {
            navigator.clipboard.writeText(text).then(flash).catch(function() { fallbackCopy(text, flash); });
          } else {
            fallbackCopy(text, flash);
          }
        });
      }
    }

    new MutationObserver(function() {
      var d = detectDark();
      if (d !== dark) update();
    }).observe(document.documentElement, {
      attributes: true,
      attributeFilter: ['class', 'data-theme', 'data-color-mode', 'style'],
    });

    update();
  }

  document.addEventListener('DOMContentLoaded', function () {
    var mount = document.getElementById('sgl-server-gen-mount');
    if (mount) render(mount);
  });
}());
