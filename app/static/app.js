const $ = (id) => document.getElementById(id);

// HUD clock — UTC, monospace, ticks every second.
(function startHudClock() {
  const tick = () => {
    const el = document.getElementById("hudClock");
    if (!el) return;
    const d = new Date();
    const pad = (n) => String(n).padStart(2, "0");
    el.textContent = `${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}:${pad(d.getUTCSeconds())} UTC`;
  };
  tick();
  setInterval(tick, 1000);
})();

const btn = $("processBtn");
const ideaEl = $("idea");
const runEl = $("run");
const statusEl = $("status");
const itersEl = $("iterations");
const finalEl = $("final");
const finalBanner = $("finalBanner");
const finalScore = $("finalScore");
const finalBrd = $("finalBrd");
const finalPremortem = $("finalPremortem");

let es = null;
let currentRunId = null;
let reconnectAttempt = 0;
let reconnectTimer = null;
let isReconnecting = false;
const iterCards = {};

const pausePanel = $("pausePanel");
const pauseSubtitle = $("pauseSubtitle");
const pauseIssues = $("pauseIssues");
const guidanceEl = $("guidance");
const continueBtn = $("continueBtn");
const skipBtn = $("skipBtn");
const timerRing = $("timerRing");
const ringProgress = $("ringProgress");
const ringLabel = $("ringLabel");

const RING_CIRCUMFERENCE = 163.36;  // 2*pi*26
let countdownInterval = null;
let userEdited = false;  // whether the user has typed in the guidance textarea

function scoreClass(s) {
  if (s >= 80) return "high";
  if (s >= 60) return "mid";
  return "low";
}

function setStatus(text, spinning = true) {
  statusEl.innerHTML = (spinning ? '<span class="spinner"></span>' : "") + text;
}

function ensureIterCard(n) {
  if (iterCards[n]) return iterCards[n];
  const card = document.createElement("div");
  card.className = "iter";
  card.innerHTML = `
    <div class="iter-header" data-n="${n}">
      <span>Iteration ${n} <span class="iter-id-chip"></span></span>
      <span class="iter-meta"></span>
    </div>
    <div class="iter-body">
      <div class="iter-status"><span class="spinner"></span>Brainstorming…</div>
      <div class="iter-brd"></div>
      <div class="iter-premortem"></div>
    </div>
  `;
  itersEl.appendChild(card);
  card.querySelector(".iter-header").addEventListener("click", () => {
    card.querySelector(".iter-body").classList.toggle("collapsed");
  });
  iterCards[n] = card;
  return card;
}

function setIterId(n, iterationId) {
  const card = ensureIterCard(n);
  const chip = card.querySelector(".iter-id-chip");
  if (chip && iterationId && !chip.textContent) {
    chip.textContent = iterationId;
    chip.title = "iteration_id (click to copy)";
    chip.addEventListener("click", (ev) => {
      ev.stopPropagation();
      navigator.clipboard?.writeText(iterationId);
      const prev = chip.textContent;
      chip.textContent = "copied";
      setTimeout(() => { chip.textContent = prev; }, 900);
    });
  }
}

function renderFlags(flags) {
  if (!flags.length) return '<div class="hint">No flags raised.</div>';
  return (
    '<div class="flags">' +
    flags
      .map(
        (f) => `
      <div class="flag ${f.severity}">
        <div><span class="title">${escapeHtml(f.title)}</span> <span class="section">— ${escapeHtml(f.section)}</span></div>
        <div><strong>Issue.</strong> ${escapeHtml(f.issue)}</div>
        <div><strong>Suggestion.</strong> ${escapeHtml(f.suggestion)}</div>
      </div>`
      )
      .join("") +
    "</div>"
  );
}

function escapeHtml(s) {
  return String(s ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

function fmtUsd(n) {
  if (n == null) return "—";
  if (n >= 1_000_000) return `$${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `$${Math.round(n / 1_000)}K`;
  return `$${n}`;
}

function vcStatus(msg) {
  const el = $("vcStatus");
  if (el) el.innerHTML = msg;
}

function renderConsensus(c) {
  const el = $("vcConsensus");
  el.innerHTML = `
    <h3>Consensus</h3>
    <div class="vc-consensus-grid">
      <div class="item">
        <div class="label">Would-fund probability</div>
        <div class="big-num">${c.would_fund_probability}%</div>
      </div>
      <div class="item">
        <div class="label">Seed valuation band (post-money)</div>
        <div class="big-num">${fmtUsd(c.consensus_valuation_low_usd)}–${fmtUsd(c.consensus_valuation_high_usd)}</div>
      </div>
      <div class="item">
        <div class="label">Typical check size</div>
        <div class="big-num">${fmtUsd(c.consensus_check_size_usd)}</div>
      </div>
    </div>
    <p><strong>Fundability.</strong> ${escapeHtml(c.fundability_summary)}</p>
    <p><strong>Biggest gating issue.</strong> ${escapeHtml(c.biggest_gating_issue)}</p>
    <div class="col-grid" style="display:grid;grid-template-columns:1fr 1fr;gap:1rem;">
      <div>
        <h4 style="margin:0 0 0.25rem;color:var(--muted);font-size:0.85rem;">Where VCs agree</h4>
        <ul style="margin:0;padding-left:1.2rem;">${(c.where_vcs_agree || []).map((b) => `<li>${escapeHtml(b)}</li>`).join("")}</ul>
      </div>
      <div>
        <h4 style="margin:0 0 0.25rem;color:var(--muted);font-size:0.85rem;">Where VCs disagree</h4>
        <ul style="margin:0;padding-left:1.2rem;">${(c.where_vcs_disagree || []).map((b) => `<li>${escapeHtml(b)}</li>`).join("")}</ul>
      </div>
    </div>
  `;
}

function renderMemo(d) {
  const e = d.eval;
  const m = e.memo;
  const p = d.profile;
  const verdictClass = e.verdict.replace(/[^a-z-]/g, "");
  const dealBreakers = (m.deal_breakers || []).length
    ? `<div class="deal-breakers"><strong>Deal breakers:</strong> ${m.deal_breakers.map(escapeHtml).join("; ")}</div>`
    : "";
  const div = document.createElement("div");
  div.className = "vc-memo";
  div.innerHTML = `
    <div class="vc-memo-header">
      <h3>${escapeHtml(p.firm)}</h3>
      <span class="verdict-pill ${verdictClass}">${escapeHtml(e.verdict)} — conviction ${e.conviction}/100</span>
    </div>
    <div class="voice">${escapeHtml(p.partner_voice)}</div>
    <div class="valuation">${fmtUsd(e.seed_valuation_low_usd)}–${fmtUsd(e.seed_valuation_high_usd)} post-money &nbsp;·&nbsp; ${fmtUsd(e.check_size_usd)} check &nbsp;·&nbsp; ${e.would_lead ? "would lead" : "would not lead"}</div>
    <div class="rationale">${escapeHtml(m.valuation_rationale)}</div>
    <div><strong>Thesis fit.</strong> ${escapeHtml(m.thesis_fit)}</div>
    <div><strong>Why matched.</strong> <span class="hint">${escapeHtml(d.match_reason)}</span></div>
    <div class="col-grid">
      <div class="col">
        <h4>What we like</h4>
        <ul>${(m.what_we_like || []).map((b) => `<li>${escapeHtml(b)}</li>`).join("")}</ul>
      </div>
      <div class="col">
        <h4>What concerns us</h4>
        <ul>${(m.what_concerns_us || []).map((b) => `<li>${escapeHtml(b)}</li>`).join("")}</ul>
      </div>
    </div>
    <div class="meta-row">
      <strong>Team lens.</strong> ${escapeHtml(m.founder_team_lens)}<br/>
      <strong>Market.</strong> ${escapeHtml(m.market_size_take)}<br/>
      <strong>Moat.</strong> ${escapeHtml(m.moat_take)}
    </div>
    ${dealBreakers}
  `;
  $("vcMemos").appendChild(div);
}

function stopCountdown() {
  if (countdownInterval) {
    clearInterval(countdownInterval);
    countdownInterval = null;
  }
}

function hideTimerRing() {
  timerRing.classList.add("hidden");
  stopCountdown();
}

function startCountdown(seconds) {
  stopCountdown();
  userEdited = false;
  timerRing.classList.remove("hidden", "expiring", "critical");
  ringProgress.style.transition = "none";
  ringProgress.style.strokeDashoffset = "0";
  ringLabel.textContent = String(seconds);
  // Force layout flush so the initial state paints before we animate.
  void ringProgress.offsetWidth;
  ringProgress.style.transition = "stroke-dashoffset 1s linear, stroke 0.3s";

  let remaining = seconds;
  const tick = () => {
    remaining -= 1;
    if (remaining < 0) {
      stopCountdown();
      // Auto-continue. The server will time out and treat as skip, but we proactively
      // submit empty guidance so the UI advances cleanly.
      if (currentRunId && !pausePanel.classList.contains("hidden")) {
        submitGuidance("", { auto: true });
      }
      return;
    }
    const elapsedFrac = (seconds - remaining) / seconds;
    ringProgress.style.strokeDashoffset = String(RING_CIRCUMFERENCE * elapsedFrac);
    ringLabel.textContent = String(remaining);
    if (remaining <= 5) {
      timerRing.classList.remove("expiring");
      timerRing.classList.add("critical");
    } else if (remaining <= 15) {
      timerRing.classList.add("expiring");
    }
  };
  countdownInterval = setInterval(tick, 1000);
}

// Cancel the timer the moment the user starts typing.
guidanceEl.addEventListener("input", () => {
  if (guidanceEl.value.length > 0 && !userEdited) {
    userEdited = true;
    stopCountdown();
    hideTimerRing();
  }
});

async function refreshCosts() {
  try {
    const r = await fetch("/costs", { cache: "no-store" });
    if (!r.ok) return;
    const d = await r.json();
    const t = d.totals_usd || {};
    $("costToday").textContent = "$" + (t.today ?? 0).toFixed(2);
    $("costWeek").textContent = "$" + (t.week ?? 0).toFixed(2);
    $("costMonth").textContent = "$" + (t.month ?? 0).toFixed(2);
  } catch {}
}
$("costStrip").addEventListener("click", refreshCosts);
refreshCosts();
setInterval(refreshCosts, 30000);

function showPausePanel(d) {
  pauseSubtitle.textContent = `Iteration ${d.n} scored ${d.score}. Review the top issues before iteration ${d.next_iteration}. Add binding strategic guidance, or skip. Auto-continues in ${d.timeout_s ?? 60}s if no input.`;
  pauseIssues.innerHTML = d.top_issues
    .map(
      (f) => `
      <li>
        <span class="pi-sev ${f.severity}">${f.severity}</span>
        <span class="pi-title">${escapeHtml(f.title)}</span>
        <span class="section">— ${escapeHtml(f.section)}</span>
        <div class="pi-issue">${escapeHtml(f.issue)}</div>
      </li>`
    )
    .join("");
  guidanceEl.value = "";
  pausePanel.classList.remove("hidden");
  continueBtn.disabled = false;
  skipBtn.disabled = false;
  pausePanel.scrollIntoView({ behavior: "smooth" });
  setStatus(`Iteration ${d.n} complete. Waiting for your strategic guidance…`, false);
  startCountdown(d.timeout_s ?? 60);
}

function hidePausePanel() {
  pausePanel.classList.add("hidden");
  stopCountdown();
}

async function submitGuidance(text, opts = {}) {
  if (!currentRunId) return;
  stopCountdown();
  continueBtn.disabled = true;
  skipBtn.disabled = true;
  if (opts.auto) {
    setStatus("Timer expired — auto-continuing with no guidance.", true);
  }
  try {
    const resp = await fetch(`/resume/${encodeURIComponent(currentRunId)}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ guidance: text }),
    });
    if (!resp.ok) {
      const msg = await resp.text();
      setStatus(`Resume failed: ${msg}`, false);
      continueBtn.disabled = false;
      skipBtn.disabled = false;
      return;
    }
    hidePausePanel();
  } catch (e) {
    setStatus(`Resume error: ${e.message}`, false);
    continueBtn.disabled = false;
    skipBtn.disabled = false;
  }
}

continueBtn.addEventListener("click", () => submitGuidance(guidanceEl.value.trim()));
skipBtn.addEventListener("click", () => submitGuidance(""));

function handlers() {
  return {
    run_started: (d) => {
      currentRunId = d.run_id;
      setStatus(`Run ${d.run_id} started. Max ${d.max_iterations} iterations, threshold ${d.threshold}.`);
    },
    awaiting_input: (d) => showPausePanel(d),
    guidance_received: (d) => {
      const card = ensureIterCard(d.n);
      const note = document.createElement("div");
      note.className = "hint";
      note.style.marginTop = "0.5rem";
      note.innerHTML = `<strong>Your guidance for next iteration:</strong> ${escapeHtml(d.guidance)}`;
      card.querySelector(".iter-body").appendChild(note);
    },
    evolution_report_started: () => {
      $("evolutionReport").innerHTML = '<div class="hint"><span class="spinner"></span>Generating evolution report…</div>';
      setStatus("Generating evolution report…");
    },
    evolution_report_done: (d) => {
      $("evolutionReport").innerHTML = marked.parse(d.report);
    },
    vc_stage_started: () => {
      $("vcSection").classList.remove("hidden");
      $("vcMemos").innerHTML = "";
      $("vcConsensus").innerHTML = "";
      vcStatus('<span class="spinner"></span>Matching top VCs for this idea…');
      setStatus("Running VC consideration…");
    },
    vc_matching: () => vcStatus('<span class="spinner"></span>Matching top VCs for this idea…'),
    vc_matched: (d) => {
      vcStatus(`Matched: ${d.matches.map((m) => `<strong>${escapeHtml(m.firm)}</strong>`).join(", ")}. Generating partner memos…`);
    },
    vc_evaluating: (d) => {
      vcStatus(`<span class="spinner"></span>Generating ${d.count} partner memo${d.count === 1 ? "" : "s"}…`);
    },
    vc_eval_done: (d) => renderMemo(d),
    vc_eval_error: (d) => {
      const div = document.createElement("div");
      div.className = "vc-memo";
      div.innerHTML = `<h3>${escapeHtml(d.firm)}</h3><div class="hint">Evaluation failed: ${escapeHtml(d.message)}</div>`;
      $("vcMemos").appendChild(div);
    },
    vc_consensus_started: () => vcStatus('<span class="spinner"></span>Synthesizing VC consensus…'),
    vc_consensus_done: (d) => {
      renderConsensus(d.consensus);
      vcStatus("VC consideration complete.");
    },
    vc_stage_error: (d) => {
      $("vcSection").classList.remove("hidden");
      vcStatus(`VC stage failed: ${escapeHtml(d.message)}`);
    },
    guidance_skipped: (d) => {
      const card = ensureIterCard(d.n);
      const note = document.createElement("div");
      note.className = "hint";
      note.style.marginTop = "0.5rem";
      note.textContent = "User skipped strategic input for next iteration.";
      card.querySelector(".iter-body").appendChild(note);
    },
    iteration_started: (d) => {
      ensureIterCard(d.n);
      setIterId(d.n, d.iteration_id);
      setStatus(`Iteration ${d.n}: brainstorming…`);
    },
    iteration_cost: (d) => {
      $("runCostVal").textContent = "$" + (d.run_cost_usd_so_far ?? 0).toFixed(4);
      const card = ensureIterCard(d.n);
      let costNote = card.querySelector(".iter-cost-note");
      if (!costNote) {
        costNote = document.createElement("div");
        costNote.className = "iter-cost-note hint";
        costNote.style.marginTop = "0.4rem";
        card.querySelector(".iter-body").appendChild(costNote);
      }
      costNote.textContent = `Iteration cost: $${(d.iteration_cost_usd ?? 0).toFixed(4)} · run so far: $${(d.run_cost_usd_so_far ?? 0).toFixed(4)}`;
    },
    brainstorm_started: (d) => {
      const card = ensureIterCard(d.n);
      card.querySelector(".iter-status").innerHTML = '<span class="spinner"></span>Brainstorming…';
    },
    brainstorm_done: (d) => {
      const card = ensureIterCard(d.n);
      card.querySelector(".iter-brd").innerHTML =
        '<details open><summary>BRD draft</summary><div class="brd">' +
        marked.parse(d.brd) +
        "</div></details>";
      card.querySelector(".iter-status").innerHTML = '<span class="spinner"></span>Running premortem…';
      setStatus(`Iteration ${d.n}: BRD draft complete, running premortem…`);
    },
    premortem_done: (d) => {
      const card = ensureIterCard(d.n);
      const cls = scoreClass(d.score);
      card.querySelector(".iter-meta").innerHTML =
        `<span class="score-pill ${cls}">Score ${d.score}</span> ` +
        `<span class="hint">${d.red_count} red, ${d.yellow_count} yellow</span>`;
      card.querySelector(".iter-status").innerHTML = `<strong>Verdict.</strong> ${escapeHtml(d.verdict)} — ${escapeHtml(d.summary)}`;
      card.querySelector(".iter-premortem").innerHTML = renderFlags(d.flags);
      // Collapse previous iterations.
      Object.entries(iterCards).forEach(([k, c]) => {
        if (Number(k) < d.n) c.querySelector(".iter-body").classList.add("collapsed");
      });
      setStatus(`Iteration ${d.n}: premortem score ${d.score}.`);
    },
    green_lit: (d) => {
      setStatus(`Green-lit at iteration ${d.n} (score ${d.score}).`, false);
    },
    cap_hit: (d) => {
      setStatus(`Iteration cap reached. Publishing best-scoring draft.`, false);
    },
    final: (d) => {
      finalEl.classList.remove("hidden");
      if (d.green_lit) {
        finalBanner.className = "banner green";
        finalBanner.textContent = `Green-lit on iteration ${d.n} (score ${d.score}). Future success score: ${d.score}/100.`;
      } else {
        finalBanner.className = "banner warn";
        finalBanner.textContent = d.warning || `Published best-scoring draft (iteration ${d.n}, score ${d.score}).`;
      }
      finalScore.innerHTML = `<span class="score-pill ${scoreClass(d.score)}">Score ${d.score}</span>`;
      finalBrd.innerHTML = marked.parse(d.brd);
      finalPremortem.innerHTML =
        `<p>${escapeHtml(d.premortem.summary)}</p>` + renderFlags(d.premortem.flags);
      const totalCost = d.cost_usd ?? 0;
      $("runCostVal").textContent = "$" + totalCost.toFixed(4);
      setStatus(`Done. ${d.total_iterations} iteration(s). Total cost $${totalCost.toFixed(4)}. Run id: ${d.run_id}.`, false);
      btn.disabled = false;
      btn.textContent = "Process this idea";
      if (es) { es.close(); es = null; }
      hidePausePanel();
      // Wire up the PDF download link now that the run is finalized server-side.
      const dlBar = $("downloadBar");
      const dlBtn = $("downloadPdfBtn");
      if (dlBar && dlBtn && d.run_id) {
        dlBtn.href = `/runs/${encodeURIComponent(d.run_id)}/report.pdf`;
        // No explicit `download` value — let the server's Content-Disposition
        // (minority_report_<project-title>.pdf) drive the filename.
        dlBtn.setAttribute("download", "");
        dlBar.classList.remove("hidden");
      }
      finalEl.scrollIntoView({ behavior: "smooth" });
      refreshCosts();  // pull updated totals into the HUD strip
    },
    error: (d) => {
      setStatus(`Error: ${d.message}`, false);
      btn.disabled = false;
      btn.textContent = "Process this idea";
      if (es) { es.close(); es = null; }
    },
  };
}

function attachEventSource(url) {
  if (reconnectTimer) { clearTimeout(reconnectTimer); reconnectTimer = null; }
  if (es) { try { es.close(); } catch {} }
  es = new EventSource(url);

  const h = handlers();
  for (const name of Object.keys(h)) {
    es.addEventListener(name, (ev) => {
      try { h[name](JSON.parse(ev.data)); } catch (e) { console.error(e, ev.data); }
    });
  }

  es.onopen = () => {
    if (isReconnecting) {
      isReconnecting = false;
      reconnectAttempt = 0;
      setStatus("Reconnected. Resuming run…");
    }
  };

  es.onerror = () => {
    // EventSource auto-reconnects per spec, but we override that behavior to
    // (a) switch to the /stream/<run_id> endpoint after the first failure,
    // (b) cap retries with exponential backoff, and (c) give the user a
    // visible "Reconnecting" status instead of silent failure.
    if (es) { try { es.close(); } catch {} es = null; }

    if (!currentRunId) {
      // We never got past the initial connect — no run to resume.
      setStatus("Connection lost before run started.", false);
      btn.disabled = false;
      btn.textContent = "Process this idea";
      return;
    }

    reconnectAttempt += 1;
    if (reconnectAttempt > 6) {
      setStatus(`Connection lost. Could not reconnect after ${reconnectAttempt - 1} tries. Run ${currentRunId} may still be running server-side — refresh and reconnect manually if needed.`, false);
      btn.disabled = false;
      btn.textContent = "Process this idea";
      return;
    }

    isReconnecting = true;
    const delayMs = Math.min(2000 * Math.pow(1.6, reconnectAttempt - 1), 15000);
    const delaySec = Math.round(delayMs / 1000);
    setStatus(`Connection lost. Reconnecting in ${delaySec}s (attempt ${reconnectAttempt})…`, true);
    reconnectTimer = setTimeout(() => {
      attachEventSource(`/stream/${encodeURIComponent(currentRunId)}`);
    }, delayMs);
  };
}

btn.addEventListener("click", () => {
  const idea = ideaEl.value.trim();
  if (!idea) { ideaEl.focus(); return; }
  const maxIterRaw = parseInt($("maxIterations").value, 10);
  const maxIterations = Number.isFinite(maxIterRaw) ? Math.min(20, Math.max(1, maxIterRaw)) : 5;

  // Reset state.
  for (const k of Object.keys(iterCards)) delete iterCards[k];
  itersEl.innerHTML = "";
  hidePausePanel();
  currentRunId = null;
  reconnectAttempt = 0;
  isReconnecting = false;
  if (reconnectTimer) { clearTimeout(reconnectTimer); reconnectTimer = null; }
  finalEl.classList.add("hidden");
  finalBanner.className = "";
  finalBanner.textContent = "";
  finalBrd.innerHTML = "";
  finalPremortem.innerHTML = "";
  $("evolutionReport").innerHTML = "";
  $("vcSection").classList.add("hidden");
  $("vcMemos").innerHTML = "";
  $("vcConsensus").innerHTML = "";
  $("downloadBar").classList.add("hidden");
  $("downloadPdfBtn").href = "#";
  $("runCostVal").textContent = "$0.0000";
  runEl.classList.remove("hidden");
  setStatus("Connecting…");
  btn.disabled = true;
  btn.textContent = "Processing…";

  attachEventSource(`/process?idea=${encodeURIComponent(idea)}&max_iterations=${maxIterations}`);
});
