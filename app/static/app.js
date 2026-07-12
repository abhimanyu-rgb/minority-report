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
// True once the server has emitted a terminal event (final / error). Stops
// the EventSource reconnect loop from chasing a run that's already dead.
let runTerminated = false;
const iterCards = {};

// ----- BRD / idea file upload -----
const uploadZone = $("uploadZone");
const uploadInput = $("uploadInput");
const uploadBrowseBtn = $("uploadBrowseBtn");
const uploadStatus = $("uploadStatus");

function setUploadStatus(msg, kind /* "success" | "error" | "info" */) {
  uploadStatus.textContent = msg;
  uploadStatus.classList.remove("hidden", "success", "error");
  if (kind === "success" || kind === "error") uploadStatus.classList.add(kind);
}

async function handleUpload(file) {
  if (!file) return;
  if (file.size > 10 * 1024 * 1024) {
    setUploadStatus(`File is ${(file.size / 1_048_576).toFixed(1)} MB; the limit is 10 MB.`, "error");
    return;
  }
  uploadZone.classList.add("busy");
  setUploadStatus(`Reading ${file.name}…`, "info");
  try {
    const form = new FormData();
    form.append("file", file);
    const resp = await fetch("/upload", { method: "POST", body: form });
    if (!resp.ok) {
      let detail = `Upload failed (HTTP ${resp.status}).`;
      try { detail = (await resp.json()).detail || detail; } catch {}
      setUploadStatus(detail, "error");
      return;
    }
    const data = await resp.json();
    if (!data || !data.attachment_id) {
      setUploadStatus(`Upload returned unexpected shape — server may need a restart.`, "error");
      return;
    }
    // New flow: backend stored the file as an attachment. Textarea stays
    // clean — it's for the user's own prompt. The attachment chip shows
    // what's attached; at Process time we send the attachment_id alongside.
    setAttachment(data);
    const kind = (data.kind || "file").toUpperCase();
    const pageBit = data.pages ? `, ${data.pages} page${data.pages === 1 ? "" : "s"}` : "";
    const briefKB = ((data.brief_chars ?? 0) / 1024).toFixed(1);
    const rawKB = ((data.raw_chars ?? 0) / 1024).toFixed(1);
    const costBit = data.distill_cost_usd
      ? ` · distilled for $${(+data.distill_cost_usd).toFixed(4)}`
      : "";
    setUploadStatus(
      `Attached ${file.name} (${kind}${pageBit}, ${rawKB} KB raw → ${briefKB} KB brief${costBit}). Type your angle below and Process.`,
      "success"
    );
  } catch (e) {
    setUploadStatus(`Upload error: ${e.message || e}`, "error");
  } finally {
    uploadZone.classList.remove("busy");
    // Reset the input so re-selecting the same file fires change again.
    uploadInput.value = "";
  }
}

uploadBrowseBtn?.addEventListener("click", (ev) => {
  ev.stopPropagation();
  uploadInput.click();
});
uploadZone?.addEventListener("click", (ev) => {
  // Clicking the zone (but not the link button) opens the picker.
  if (ev.target.closest(".link-btn")) return;
  uploadInput.click();
});
uploadInput?.addEventListener("change", () => handleUpload(uploadInput.files?.[0]));
["dragenter", "dragover"].forEach((evt) => {
  uploadZone?.addEventListener(evt, (e) => {
    e.preventDefault();
    e.stopPropagation();
    uploadZone.classList.add("dragging");
  });
});
["dragleave", "drop"].forEach((evt) => {
  uploadZone?.addEventListener(evt, (e) => {
    e.preventDefault();
    e.stopPropagation();
    uploadZone.classList.remove("dragging");
  });
});
uploadZone?.addEventListener("drop", (e) => {
  const file = e.dataTransfer?.files?.[0];
  handleUpload(file);
});

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
        <h4>To iron out</h4>
        <ul>${((m.to_iron_out || m.what_concerns_us) || []).map((b) => `<li>${escapeHtml(b)}</li>`).join("")}</ul>
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

// Once the user touches the guidance textarea in any way (typing, pasting,
// even pressing a modifier), kill the auto-continue timer for the rest of
// this iteration. The user must press Continue or Skip explicitly to advance.
//
// Why permanent (not reset-on-keystroke): if you take 90 seconds to write a
// thoughtful response, a sliding window would still fire while you were
// mid-sentence. Once we know you're actively engaging, the right policy is
// to wait for an explicit signal from you.
//
// CRITICAL: we also POST /heartbeat/<run_id> so the *server* knows to
// suspend its own auto-skip deadline. Without the heartbeat, the client's
// visible timer goes away but the server still times out at 60s and
// auto-advances the loop — wiping the user's in-progress text. The
// heartbeat closes that loop.
function killAutoContinue() {
  if (!userEdited) {
    userEdited = true;
    stopCountdown();
    hideTimerRing();
    // Replace the auto-continue note in the subtitle with a static reminder
    // so the user knows the timer is intentionally disabled.
    if (pauseSubtitle && pauseSubtitle.textContent.includes("Auto-continues")) {
      pauseSubtitle.textContent = pauseSubtitle.textContent.replace(
        / Auto-continues in \d+s if no input\.?/,
        " Timer paused while you're typing — press Continue or Skip when ready."
      );
    }
  }
  // Heartbeat the server. Fire-and-forget; the server treats unknown/stale
  // run_ids as a harmless no-op.
  if (currentRunId) {
    fetch(`/heartbeat/${encodeURIComponent(currentRunId)}`, { method: "POST", keepalive: true })
      .catch(() => {});
  }
}

// Fire on every plausible signal that the user is actually entering content.
// `keydown` catches the very first key (including modifier-only presses like
// Shift before a capital letter) — `input` alone misses IME composition
// starts and some paste edge cases. We intentionally do NOT listen on `focus`
// because clicking-to-read shouldn't kill the timer.
["keydown", "input", "paste", "cut"].forEach((evt) =>
  guidanceEl.addEventListener(evt, killAutoContinue)
);

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
    vc_skipped: () => {
      $("vcSection").classList.add("hidden");
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
        const vcVisible = !$("vcSection").classList.contains("hidden");
        const sub = dlBar.querySelector(".sub");
        if (sub) {
          sub.textContent = vcVisible
            ? "Cover · Final BRD · Evolution · VC consideration"
            : "Cover · Final BRD · Evolution";
        }
        dlBar.classList.remove("hidden");
      }
      if (typeof window.__showFeedback === "function") {
        window.__showFeedback(d.total_iterations || 1);
      }
      if (typeof window.__showRefinePanel === "function") {
        window.__showRefinePanel();
      }
      finalEl.scrollIntoView({ behavior: "smooth" });
      refreshCosts();  // pull updated totals into the HUD strip
      // Notify if user wandered off mid-run.
      try {
        if (document.hidden && "Notification" in window && Notification.permission === "granted") {
          const score = d.score ?? "—";
          const verdict = d.green_lit ? "Green-lit" : "Best draft";
          new Notification("Minority Report — run complete", {
            body: `${verdict} · score ${score} · ${d.total_iterations || 1} iter(s).`,
            tag: `run-${d.run_id}`,
          });
        }
      } catch (e) { /* ignore */ }
      const sb = $("stopBtn"); if (sb) sb.classList.add("hidden");
      runTerminated = true;
      if (reconnectTimer) { clearTimeout(reconnectTimer); reconnectTimer = null; }
    },
    error: (d) => {
      // Friendlier copy for known hard-failure cases.
      let msg = d.message || "Unknown error.";
      if (/usage limits|workspace.*limit|quota/i.test(msg)) {
        msg = `Anthropic workspace usage limit reached. Run halted. Raise the cap at console.anthropic.com/settings/limits, or wait for it to reset.\n\nFull message: ${msg}`;
      } else if (/401|unauthorized|invalid.*key/i.test(msg)) {
        msg = `Anthropic API rejected the key as unauthorized. Check ANTHROPIC_API_KEY in .env and restart the server.\n\nFull message: ${msg}`;
      } else if (/429|rate.?limit/i.test(msg)) {
        msg = `Anthropic rate-limited the call. Try again in a minute.\n\nFull message: ${msg}`;
      }
      setStatus(`Error: ${msg}`, false);
      runTerminated = true;
      if (reconnectTimer) { clearTimeout(reconnectTimer); reconnectTimer = null; }
      isReconnecting = false;
      btn.disabled = false;
      btn.textContent = "Process this idea";
      if (es) { try { es.close(); } catch {} es = null; }
      const sb = $("stopBtn"); if (sb) sb.classList.add("hidden");
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
    if (es) { try { es.close(); } catch {} es = null; }

    // If the run already finished or errored, the server closed the stream
    // intentionally. Don't try to reconnect — there's nothing left to receive.
    if (runTerminated) {
      isReconnecting = false;
      return;
    }

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
  // Allow empty idea ONLY if there's an attachment — the server will use
  // the attachment's brief as the idea in that case.
  if (!idea && !(typeof __attachment === "object" && __attachment && __attachment.attachment_id)) {
    ideaEl.focus();
    return;
  }
  const maxIterRaw = parseInt($("maxIterations").value, 10);
  const maxIterations = Number.isFinite(maxIterRaw) ? Math.min(20, Math.max(1, maxIterRaw)) : 5;
  const vcEnabledEl = $("vcEnabled");
  const vcEnabled = vcEnabledEl ? vcEnabledEl.checked : true;

  // Reset state.
  for (const k of Object.keys(iterCards)) delete iterCards[k];
  itersEl.innerHTML = "";
  hidePausePanel();
  currentRunId = null;
  reconnectAttempt = 0;
  isReconnecting = false;
  runTerminated = false;
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
  if (typeof window.__hideFeedback === "function") window.__hideFeedback();
  if (typeof window.__hideRefinePanel === "function") window.__hideRefinePanel();
  $("runCostVal").textContent = "$0.0000";
  runEl.classList.remove("hidden");
  setStatus("Connecting…");
  btn.disabled = true;
  btn.textContent = "Processing…";
  // Show the Stop button for the duration of this run.
  const stopBtn = $("stopBtn");
  if (stopBtn) {
    stopBtn.classList.remove("hidden");
    stopBtn.disabled = false;
    stopBtn.textContent = "⏹ Stop run";
  }

  // Best-effort: request notification permission once per session.
  try {
    if ("Notification" in window && Notification.permission === "default") {
      Notification.requestPermission();
    }
  } catch (e) { /* ignore */ }

  // POST the run params in a JSON body to avoid querystring length limits
  // (long PDF-extracted ideas would otherwise blow past the ~8 KB request-line
  // cap and uvicorn would reject the request before any handler ran).
  startRun({
    idea,
    max_iterations: maxIterations,
    vc_enabled: vcEnabled ? "1" : "0",
    user_id: __identity ? __identity.user_id : "",
    persona: __identity ? __identity.persona : "",
    sector: $("tagSector")?.value || "",
    stage: $("tagStage")?.value || "",
    theme: $("tagTheme")?.value || "",
  });
});

async function startRun(body) {
  try {
    const res = await fetch("/runs/create", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!res.ok) {
      const j = await res.json().catch(() => ({}));
      setStatus(`Failed to start run: ${j.detail || res.status}`, false);
      btn.disabled = false;
      btn.textContent = "Process this idea";
      const sb = $("stopBtn"); if (sb) sb.classList.add("hidden");
      return;
    }
    const { run_id } = await res.json();
    currentRunId = run_id;
    attachEventSource(`/stream/${encodeURIComponent(run_id)}`);
  } catch (e) {
    setStatus(`Network error starting run: ${e.message}`, false);
    btn.disabled = false;
    btn.textContent = "Process this idea";
    const sb = $("stopBtn"); if (sb) sb.classList.add("hidden");
  }
}

// =============================================================================
// TABS — switch between New-run panel and Analytics
// =============================================================================
// (Tab wiring lives in wireFiveTabs further below — keep one canonical wiring.)

// =============================================================================
// ANALYTICS RENDERING
// =============================================================================
async function refreshAnalytics() {
  if (!__identity) return;
  try {
    const uid = encodeURIComponent(__identity.user_id);
    const [aRes, pRes] = await Promise.all([
      fetch(`/analytics?user_id=${uid}`, { cache: "no-store" }),
      fetch("/analytics/flag-patterns", { cache: "no-store" }),
    ]);
    if (aRes.status === 403) {
      console.warn("admin access denied for", __identity.user_id);
      return;
    }
    const a = await aRes.json();
    const p = await pRes.json();
    renderAnalytics(a, p);
  } catch (e) {
    console.error("analytics refresh failed", e);
  }
}

function renderAnalytics(a, p) {
  const t = a.totals || {};
  const fmt = (n) => `$${(n || 0).toFixed(2)}`;
  $("anTotalRuns").textContent = (t.all_time && t.all_time.runs) || 0;
  $("anTotalRunsSub").textContent =
    `${(t.all_time && t.all_time.completed) || 0} completed · ${(t.all_time && t.all_time.green_lit) || 0} green-lit`;
  $("anMonthRuns").textContent = (t.this_month && t.this_month.runs) || 0;
  $("anMonthCost").textContent = fmt(t.this_month && t.this_month.cost_usd);
  $("anAllCost").textContent = fmt(t.all_time && t.all_time.cost_usd);
  $("anWeekCost").textContent = `${fmt(t.this_week && t.this_week.cost_usd)} this week`;

  const fb = a.feedback || { up: 0, down: 0, total: 0 };
  $("anFeedback").textContent = `${fb.up} 👍 · ${fb.down} 👎`;
  $("anFeedbackSub").textContent = `${fb.total} ratings`;

  // ----- Cost KPIs -----
  const ck = a.cost_kpis || {};
  const dash = "—";
  const usd = (v) => (v === null || v === undefined ? "$—" : `$${(+v).toFixed(2)}`);
  $("kpiAvgCost").textContent = usd(ck.avg_cost_per_run);
  $("kpiAvgCostSub").textContent = `${ck.sample_size_runs || 0} runs sampled`;
  $("kpiCostP").textContent = `${usd(ck.p50_cost_per_run)} · ${usd(ck.p95_cost_per_run)}`;
  $("kpiMaxCost").textContent = usd(ck.max_cost_per_run);
  $("kpiMinCostSub").textContent = `Min: ${usd(ck.min_cost_per_run)}`;
  $("kpiAvgIterCost").textContent = usd(ck.avg_cost_per_iteration);
  $("kpiAvgIterCostSub").textContent = `${ck.sample_size_iters || 0} iterations sampled`;

  // ----- Quality KPIs -----
  const qk = a.quality_kpis || {};
  const pct = (v) => (v === null || v === undefined ? `${dash}%` : `${(+v).toFixed(1)}%`);
  const numOrDash = (v) => (v === null || v === undefined ? dash : (+v).toFixed(1));
  $("kpiGreenRate").textContent = pct(qk.green_light_rate_pct);
  $("kpiCapHitSub").textContent = `Cap-hit: ${pct(qk.cap_hit_rate_pct)}`;
  $("kpiAvgScore").textContent = numOrDash(qk.avg_final_score);
  $("kpiAvgIters").textContent = numOrDash(qk.avg_iterations_all);
  $("kpiAvgItersSub").textContent = `Green-lit only: ${numOrDash(qk.avg_iterations_green_lit)}`;
  const lift = qk.avg_score_lift_v1_to_final;
  $("kpiLift").textContent =
    lift === null || lift === undefined ? dash : (lift > 0 ? "+" : "") + (+lift).toFixed(1);
  $("kpiLiftSub").textContent = `${qk.score_lift_sample || 0} multi-iter runs`;

  // ----- Engagement / speed -----
  const ek = a.engagement_kpis || {};
  $("kpiGuidanceRate").textContent = pct(ek.guidance_rate_pct);
  $("kpiGuidanceRateSub").textContent = `${ek.pauses_with_guidance || 0} / ${ek.pauses_total || 0} pauses`;
  $("kpiGuidanceLen").textContent =
    ek.avg_guidance_chars === null || ek.avg_guidance_chars === undefined
      ? `${dash} chars`
      : `${Math.round(ek.avg_guidance_chars)} chars`;
  const sk = a.speed_kpis || {};
  const fmtSeconds = (v) => {
    if (v === null || v === undefined) return dash;
    if (v >= 60) return `${(v / 60).toFixed(1)} min`;
    return `${(+v).toFixed(0)}s`;
  };
  $("kpiAvgWall").textContent = fmtSeconds(sk.avg_seconds_per_run);
  $("kpiWallPSub").textContent = `P95: ${fmtSeconds(sk.p95_seconds_per_run)}`;
  $("kpiAvgIterWall").textContent = fmtSeconds(sk.avg_seconds_per_iteration);

  renderSparkline(a.rolling_mean_7d || []);
  renderHistogram(a.score_distribution || []);

  const tf = $("topFlags");
  tf.innerHTML = "";
  (a.top_flags || []).forEach((f) => {
    const li = document.createElement("li");
    li.innerHTML = `${escapeHtml(f.title)} <span class="count">×${f.count}</span>`;
    tf.appendChild(li);
  });
  if (!a.top_flags || !a.top_flags.length) tf.innerHTML = "<li class='hint'>No flags yet.</li>";

  const meta = a.flag_patterns_meta || {};
  $("priorsMeta").textContent = meta.feedback_gate_active
    ? `Feedback gate ACTIVE — 👎 runs excluded. ${meta.pattern_count || 0} patterns · ${meta.total_runs_considered || 0} runs contributing.`
    : `Feedback gate not yet active (${meta.feedback_runs || 0}/10 ratings). ${meta.pattern_count || 0} patterns · ${meta.total_runs_considered || 0} runs contributing.`;

  const pl = $("priorList");
  pl.innerHTML = "";
  (p.patterns || []).slice(0, 8).forEach((pat) => {
    const li = document.createElement("li");
    li.innerHTML = `<strong>${escapeHtml(pat.title)}</strong> <span class="meta">[${escapeHtml(pat.section || "—")}] · ${pat.dominant_severity.toUpperCase()} · ${pat.run_count}/${meta.total_runs_considered || "?"} runs</span>`;
    pl.appendChild(li);
  });
  if (!p.patterns || !p.patterns.length) pl.innerHTML = "<li class='hint'>No priors yet — needs more runs.</li>";

  const fn = $("feedbackNotes");
  fn.innerHTML = "";
  (fb.recent_notes || []).forEach((n) => {
    const li = document.createElement("li");
    const mark = n.rating === "up" ? "👍" : n.rating === "down" ? "👎" : "·";
    li.innerHTML = `<span class="rating-mark">${mark}</span>${escapeHtml(n.note)}<span class="ts">${escapeHtml((n.submitted_at || "").slice(0, 19))}</span>`;
    fn.appendChild(li);
  });
  if (!fb.recent_notes || !fb.recent_notes.length) fn.innerHTML = "<li class='hint'>No notes yet.</li>";
}

function renderSparkline(series) {
  const svg = $("sparkline");
  svg.innerHTML = "";
  const W = 600, H = 120, PAD = 6;
  const points = series.filter((d) => d.rolling_mean_7d !== null);
  if (!points.length) {
    const t = document.createElementNS("http://www.w3.org/2000/svg", "text");
    t.setAttribute("x", W / 2);
    t.setAttribute("y", H / 2);
    t.setAttribute("text-anchor", "middle");
    t.setAttribute("fill", "#8aa3b8");
    t.setAttribute("font-size", "12");
    t.textContent = "Not enough data yet.";
    svg.appendChild(t);
    $("sparklineAxis").innerHTML = "";
    return;
  }
  // Y-axis: 0-100 score
  const xStep = (W - 2 * PAD) / Math.max(1, series.length - 1);
  const y = (v) => H - PAD - ((v / 100) * (H - 2 * PAD));
  // Build path
  let d = "";
  series.forEach((pt, i) => {
    const xv = PAD + i * xStep;
    if (pt.rolling_mean_7d === null) return;
    d += `${d ? "L" : "M"}${xv.toFixed(2)} ${y(pt.rolling_mean_7d).toFixed(2)} `;
  });
  // Threshold line at 80
  const thr = document.createElementNS("http://www.w3.org/2000/svg", "line");
  thr.setAttribute("x1", PAD); thr.setAttribute("x2", W - PAD);
  thr.setAttribute("y1", y(80)); thr.setAttribute("y2", y(80));
  thr.setAttribute("stroke", "rgba(255,184,107,0.4)");
  thr.setAttribute("stroke-dasharray", "4 4");
  svg.appendChild(thr);
  // Path
  const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
  path.setAttribute("d", d.trim());
  path.setAttribute("fill", "none");
  path.setAttribute("stroke", "#6fd8ff");
  path.setAttribute("stroke-width", "2");
  path.setAttribute("filter", "drop-shadow(0 0 4px rgba(111,216,255,0.6))");
  svg.appendChild(path);
  // Axis labels: first/last date with data
  const axis = $("sparklineAxis");
  axis.innerHTML = "";
  const start = document.createElement("span");
  start.textContent = series[0] ? series[0].date : "";
  const end = document.createElement("span");
  end.textContent = series[series.length - 1] ? series[series.length - 1].date : "";
  axis.appendChild(start);
  axis.appendChild(end);
}

function renderHistogram(dist) {
  const el = $("histogram");
  el.innerHTML = "";
  const max = Math.max(1, ...dist);
  const labels = ["0", "10", "20", "30", "40", "50", "60", "70", "80", "90"];
  dist.forEach((c, i) => {
    const bar = document.createElement("div");
    bar.className = "hbar";
    const pct = (c / max) * 100;
    bar.style.height = `${Math.max(2, pct)}%`;
    bar.innerHTML = `<span class="hbar-count">${c || ""}</span><span class="hbar-label">${labels[i]}</span>`;
    el.appendChild(bar);
  });
}

// =============================================================================
// FEEDBACK PANEL
// =============================================================================
(function wireFeedback() {
  let selectedRating = null;
  let bound = false;
  const panel = $("feedbackPanel");
  const upBtn = $("ratingUp");
  const downBtn = $("ratingDown");
  const actedBtn = $("ratingActed");
  const submitBtn = $("feedbackSubmitBtn");
  const noteEl = $("feedbackNote");
  const statusEl = $("feedbackStatus");
  const selectEl = $("feedbackMostUseful");

  function setSelected(rating) {
    selectedRating = rating;
    upBtn.classList.toggle("selected", rating === "up");
    downBtn.classList.toggle("selected", rating === "down");
    if (actedBtn) actedBtn.classList.toggle("selected", rating === "acted_on");
    submitBtn.disabled = !rating;
  }

  upBtn.addEventListener("click", () => setSelected("up"));
  downBtn.addEventListener("click", () => setSelected("down"));
  if (actedBtn) actedBtn.addEventListener("click", () => setSelected("acted_on"));

  submitBtn.addEventListener("click", async () => {
    if (!currentRunId || !selectedRating) return;
    submitBtn.disabled = true;
    statusEl.textContent = "Submitting…";
    try {
      const body = {
        rating: selectedRating,
        note: noteEl.value.trim(),
        most_useful_iteration_n: selectEl.value ? parseInt(selectEl.value, 10) : null,
      };
      const res = await fetch(`/feedback/${encodeURIComponent(currentRunId)}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      statusEl.textContent = "Thanks — feedback saved.";
      upBtn.disabled = true;
      downBtn.disabled = true;
      if (actedBtn) actedBtn.disabled = true;
      noteEl.disabled = true;
      selectEl.disabled = true;
    } catch (e) {
      statusEl.textContent = `Failed: ${e.message}`;
      submitBtn.disabled = false;
    }
  });

  // Expose helpers used from the final handler.
  window.__showFeedback = (iterationCount) => {
    panel.classList.remove("hidden");
    // Reset state in case the user runs again.
    setSelected(null);
    upBtn.disabled = false;
    downBtn.disabled = false;
    if (actedBtn) actedBtn.disabled = false;
    noteEl.disabled = false;
    selectEl.disabled = false;
    noteEl.value = "";
    statusEl.textContent = "";
    // Populate iteration dropdown.
    selectEl.innerHTML = '<option value="">—</option>';
    for (let i = 1; i <= iterationCount; i++) {
      const o = document.createElement("option");
      o.value = String(i);
      o.textContent = `Iteration ${i}`;
      selectEl.appendChild(o);
    }
  };
  window.__hideFeedback = () => panel.classList.add("hidden");
})();

// =============================================================================
// IDENTITY — name/email + persona, stored in localStorage
// =============================================================================
const IDENTITY_KEY = "mr.identity.v1";
let __identity = null;     // { user_id, persona }
let __personas = [];       // from /personas

function loadIdentity() {
  try {
    const raw = localStorage.getItem(IDENTITY_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (parsed && parsed.user_id && parsed.persona) return parsed;
  } catch (e) { /* fall through */ }
  return null;
}

function saveIdentity(id) {
  __identity = id;
  try { localStorage.setItem(IDENTITY_KEY, JSON.stringify(id)); } catch (e) {}
  renderIdentityStrip();
  refreshAdminTabVisibility();
}

async function refreshAdminTabVisibility() {
  const tab = $("adminTab");
  if (!tab) return;
  if (!__identity) {
    tab.classList.add("hidden");
    return;
  }
  try {
    const res = await fetch(`/whoami?user_id=${encodeURIComponent(__identity.user_id)}`);
    const j = await res.json();
    tab.classList.toggle("hidden", !j.is_admin);
  } catch (e) {
    tab.classList.add("hidden");
  }
}

function renderIdentityStrip() {
  const strip = $("identityStrip");
  if (!strip) return;
  if (!__identity) {
    strip.style.display = "none";
    return;
  }
  strip.style.display = "";
  $("identityName").textContent = __identity.user_id;
  const p = __personas.find((x) => x.id === __identity.persona);
  $("identityPersona").textContent = p ? p.label : __identity.persona;
}

async function fetchPersonas() {
  try {
    const res = await fetch("/personas");
    const j = await res.json();
    __personas = j.personas || [];
  } catch (e) { __personas = []; }
}

function openIdentityModal() {
  const modal = $("identityModal");
  const grid = $("personaGrid");
  const nameEl = $("identityNameInput");
  grid.innerHTML = "";
  let pickedPersona = (__identity && __identity.persona) || null;
  __personas.forEach((p) => {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "persona-pick" + (p.id === pickedPersona ? " selected" : "");
    b.innerHTML = `<span class="persona-title">${escapeHtml(p.label)}</span><span class="persona-baseline">baseline ${p.baseline_minutes} min</span>`;
    b.addEventListener("click", () => {
      grid.querySelectorAll(".persona-pick").forEach((x) => x.classList.remove("selected"));
      b.classList.add("selected");
      pickedPersona = p.id;
    });
    grid.appendChild(b);
  });
  nameEl.value = (__identity && __identity.user_id) || "";
  modal.classList.remove("hidden");
  setTimeout(() => nameEl.focus(), 50);

  const saveBtn = $("identitySaveBtn");
  const onSave = () => {
    const uid = (nameEl.value || "").trim();
    if (!uid || !pickedPersona) {
      nameEl.focus();
      return;
    }
    saveIdentity({ user_id: uid, persona: pickedPersona });
    modal.classList.add("hidden");
    saveBtn.removeEventListener("click", onSave);
  };
  saveBtn.addEventListener("click", onSave);
}

(async function bootIdentity() {
  await fetchPersonas();
  __identity = loadIdentity();
  renderIdentityStrip();
  refreshAdminTabVisibility();
  const changeBtn = $("identityChangeBtn");
  if (changeBtn) changeBtn.addEventListener("click", openIdentityModal);
  if (!__identity) openIdentityModal();
})();

// Patch the process call to include identity.
(function patchProcessForIdentity() {
  const origBtn = btn;
  const origHandler = origBtn.onclick;
  // We already attached a click handler with addEventListener; intercept the
  // attachEventSource call by overriding it.
})();
const _origAttachEventSource = attachEventSource;
attachEventSource = function patched(url) {
  if (__identity && url.startsWith("/process?")) {
    url += `&user_id=${encodeURIComponent(__identity.user_id)}&persona=${encodeURIComponent(__identity.persona)}`;
  }
  return _origAttachEventSource(url);
};

// (Tab wiring lives in wireFiveTabs further below — keep one canonical wiring.)
// Wire the user-analytics-refresh button here since it isn't a tab.
(function wireUserAnalyticsRefresh() {
  const userRefresh = $("userAnalyticsRefreshBtn");
  if (userRefresh) userRefresh.addEventListener("click", refreshUserAnalytics);
  const adminRefresh = $("analyticsRefreshBtn");
  if (adminRefresh) adminRefresh.addEventListener("click", refreshAnalytics);
})();

// =============================================================================
// USER ANALYTICS RENDERING
// =============================================================================
async function refreshUserAnalytics() {
  if (!__identity) {
    openIdentityModal();
    return;
  }
  try {
    const res = await fetch(
      `/analytics/user?user_id=${encodeURIComponent(__identity.user_id)}&persona=${encodeURIComponent(__identity.persona)}`,
      { cache: "no-store" }
    );
    const a = await res.json();
    renderUserAnalytics(a);
  } catch (e) {
    console.error("user analytics refresh failed", e);
  }
}

function renderUserAnalytics(a) {
  const who = `${__identity.user_id} · ${__personas.find((x) => x.id === __identity.persona)?.label || __identity.persona}`;
  $("userAnalyticsWho").textContent = `· ${who}`;

  const u = a.user_kpis || {};
  const dash = "—";
  $("uaTimeSaved").textContent = u.time_saved_hours ? `${u.time_saved_hours} hrs` : `${dash} hrs`;
  $("uaTimeSavedSub").textContent = u.time_saved_minutes ? `Across ${u.reports_completed || 0} reports` : "Versus drafting manually";
  $("uaReports").textContent = u.reports_completed || 0;
  $("uaReportsSub").textContent = `${u.reports_this_month || 0} this month · ${u.reports_this_week || 0} this week`;
  $("uaActedRate").textContent = `${(u.acted_on_rate_pct || 0).toFixed(1)}%`;
  $("uaActedSub").textContent = `${u.acted_on_count || 0} marked acted-on`;
  $("uaVelocity").textContent = u.decision_velocity_per_week ?? 0;
  $("uaGreenRate").textContent = `${(u.green_light_rate_pct || 0).toFixed(1)}%`;

  // Score trend: last vs first
  const sp = u.score_progression || [];
  if (sp.length >= 2) {
    const delta = sp[sp.length - 1].score - sp[0].score;
    $("uaTrend").textContent = (delta > 0 ? "+" : "") + delta;
    $("uaTrendSub").textContent = `${sp[0].score} → ${sp[sp.length - 1].score}`;
  } else {
    $("uaTrend").textContent = dash;
    $("uaTrendSub").textContent = "Need 2+ reports";
  }

  // Sparkline of score progression (different from rolling mean: raw scores per run)
  renderRawSparkline("uaScoreSpark", "uaScoreSparkAxis", sp);

  // Top flags filtered to this user's runs
  const tf = $("uaTopFlags");
  tf.innerHTML = "";
  (a.top_flags || []).forEach((f) => {
    const li = document.createElement("li");
    li.innerHTML = `${escapeHtml(f.title)} <span class="count">×${f.count}</span>`;
    tf.appendChild(li);
  });
  if (!a.top_flags || !a.top_flags.length) tf.innerHTML = "<li class='hint'>Run more reports to surface patterns.</li>";

  // Recent runs
  const rl = $("uaRecentRuns");
  rl.innerHTML = "";
  (u.recent_runs || []).forEach((r) => {
    const li = document.createElement("li");
    const badge = r.green_lit
      ? `<span class="rl-badge green">Green-lit</span>`
      : `<span class="rl-badge warn">Best draft</span>`;
    li.innerHTML = `
      <span class="rl-date">${escapeHtml((r.started_at || "").slice(0, 10))}</span>
      <span class="rl-score">${r.final_score ?? "—"}</span>
      ${badge}
      <span class="rl-meta">${r.total_iterations || "—"} iter · $${(r.cost_usd || 0).toFixed(2)}</span>
      <a class="rl-pdf" href="/runs/${encodeURIComponent(r.run_id)}/report.pdf" download>PDF</a>
    `;
    rl.appendChild(li);
  });
  if (!u.recent_runs || !u.recent_runs.length) rl.innerHTML = "<li class='hint'>No reports yet — run your first idea.</li>";
}

function renderRawSparkline(svgId, axisId, series) {
  const svg = $(svgId);
  svg.innerHTML = "";
  const W = 600, H = 120, PAD = 6;
  if (!series.length) {
    const t = document.createElementNS("http://www.w3.org/2000/svg", "text");
    t.setAttribute("x", W / 2); t.setAttribute("y", H / 2);
    t.setAttribute("text-anchor", "middle"); t.setAttribute("fill", "#8aa3b8");
    t.setAttribute("font-size", "12");
    t.textContent = "No reports yet.";
    svg.appendChild(t);
    $(axisId).innerHTML = "";
    return;
  }
  const xStep = (W - 2 * PAD) / Math.max(1, series.length - 1);
  const y = (v) => H - PAD - ((v / 100) * (H - 2 * PAD));
  // Threshold at 80
  const thr = document.createElementNS("http://www.w3.org/2000/svg", "line");
  thr.setAttribute("x1", PAD); thr.setAttribute("x2", W - PAD);
  thr.setAttribute("y1", y(80)); thr.setAttribute("y2", y(80));
  thr.setAttribute("stroke", "rgba(255,184,107,0.4)"); thr.setAttribute("stroke-dasharray", "4 4");
  svg.appendChild(thr);
  // Line
  let d = "";
  series.forEach((pt, i) => {
    const xv = PAD + i * xStep;
    d += `${d ? "L" : "M"}${xv.toFixed(2)} ${y(pt.score).toFixed(2)} `;
  });
  const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
  path.setAttribute("d", d.trim()); path.setAttribute("fill", "none");
  path.setAttribute("stroke", "#6fd8ff"); path.setAttribute("stroke-width", "2");
  path.setAttribute("filter", "drop-shadow(0 0 4px rgba(111,216,255,0.6))");
  svg.appendChild(path);
  // Dots
  series.forEach((pt, i) => {
    const c = document.createElementNS("http://www.w3.org/2000/svg", "circle");
    c.setAttribute("cx", PAD + i * xStep); c.setAttribute("cy", y(pt.score));
    c.setAttribute("r", 3); c.setAttribute("fill", "#aeefff");
    svg.appendChild(c);
  });
  const axis = $(axisId);
  axis.innerHTML = "";
  const start = document.createElement("span"); start.textContent = series[0].date;
  const end = document.createElement("span"); end.textContent = series[series.length - 1].date;
  axis.appendChild(start); axis.appendChild(end);
}

// (acted_on button handled inside wireFeedback above)

// =============================================================================
// WAVE 3 — TAG INTAKE, RUNS LIST, OUTCOMES, RUBRIC, PRIORS TRANSPARENCY
// =============================================================================

let __taxonomy = { sectors: [], stages: [] };

async function fetchTaxonomy() {
  try {
    const res = await fetch("/taxonomy");
    __taxonomy = await res.json();
  } catch (e) { __taxonomy = { sectors: [], stages: [] }; }
}

function populateTagDropdowns() {
  const sec = $("tagSector");
  const stg = $("tagStage");
  const filtSec = $("runsFilterSector");
  const filtStg = $("runsFilterStage");
  if (sec) {
    sec.innerHTML = "";
    __taxonomy.sectors.forEach((s) => {
      const o = document.createElement("option");
      o.value = s.id; o.textContent = s.label;
      sec.appendChild(o);
    });
  }
  if (stg) {
    stg.innerHTML = "";
    __taxonomy.stages.forEach((s) => {
      const o = document.createElement("option");
      o.value = s.id; o.textContent = s.label;
      stg.appendChild(o);
    });
  }
  if (filtSec) {
    filtSec.innerHTML = '<option value="">All sectors</option>';
    __taxonomy.sectors.forEach((s) => {
      const o = document.createElement("option");
      o.value = s.id; o.textContent = s.label;
      filtSec.appendChild(o);
    });
  }
  if (filtStg) {
    filtStg.innerHTML = '<option value="">All stages</option>';
    __taxonomy.stages.forEach((s) => {
      const o = document.createElement("option");
      o.value = s.id; o.textContent = s.label;
      filtStg.appendChild(o);
    });
  }
}

// Append tag params to the /process URL through the existing attachEventSource shim.
const _origAttach2 = attachEventSource;
attachEventSource = function patchedTags(url) {
  if (url.startsWith("/process?")) {
    const sec = $("tagSector")?.value || "";
    const stg = $("tagStage")?.value || "";
    const thm = $("tagTheme")?.value || "";
    if (sec) url += `&sector=${encodeURIComponent(sec)}`;
    if (stg) url += `&stage=${encodeURIComponent(stg)}`;
    if (thm) url += `&theme=${encodeURIComponent(thm)}`;
  }
  return _origAttach2(url);
};

// ---------- Tab switcher (extended to 5 tabs) ----------
(function wireFiveTabs() {
  document.querySelectorAll(".tabs .tab").forEach((t) => {
    const clone = t.cloneNode(true);
    t.parentNode.replaceChild(clone, t);
  });
  const intake = $("intake");
  const runPanel = $("run");
  const finalPanel = $("final");
  const myRuns = $("myRunsPanel");
  const userPanel = $("userAnalyticsPanel");
  const rubricPanel = $("rubricPanel");
  const adminPanel = $("analyticsPanel");
  const identityStrip = $("identityStrip");

  function show(which) {
    document.querySelectorAll(".tabs .tab").forEach((t) =>
      t.classList.toggle("active", t.dataset.tab === which)
    );
    [intake, runPanel, finalPanel, myRuns, userPanel, rubricPanel, adminPanel].forEach(
      (p) => p && p.classList.add("hidden")
    );
    if (which === "run") {
      intake && intake.classList.remove("hidden");
      identityStrip.style.display = __identity ? "" : "none";
    } else if (which === "my-runs") {
      myRuns.classList.remove("hidden");
      refreshMyRuns();
    } else if (which === "user-analytics") {
      userPanel.classList.remove("hidden");
      refreshUserAnalytics();
    } else if (which === "rubric") {
      rubricPanel.classList.remove("hidden");
      refreshRubric();
    } else if (which === "admin") {
      adminPanel.classList.remove("hidden");
      refreshAnalytics();
    }
  }
  document.querySelectorAll(".tabs .tab").forEach((t) =>
    t.addEventListener("click", () => show(t.dataset.tab))
  );
  $("myRunsRefreshBtn")?.addEventListener("click", refreshMyRuns);
  ["runsSearch", "runsFilterSector", "runsFilterStage", "runsFilterOutcome"].forEach((id) =>
    $(id)?.addEventListener("change", refreshMyRuns)
  );
  $("runsSearch")?.addEventListener("input", debounce(refreshMyRuns, 300));
})();

function debounce(fn, ms) {
  let h;
  return (...args) => { clearTimeout(h); h = setTimeout(() => fn(...args), ms); };
}

// ---------- Toggle rubric tab visibility based on persona ----------
function refreshRubricTabVisibility() {
  const tab = $("rubricTab");
  if (!tab) return;
  const show = !!(__identity && __identity.persona === "investor");
  tab.classList.toggle("hidden", !show);
}

// Hook into existing identity saving + boot so rubric visibility updates.
const _origSaveIdentity = saveIdentity;
saveIdentity = function patched(id) {
  _origSaveIdentity(id);
  refreshRubricTabVisibility();
};
refreshRubricTabVisibility();  // initial

// ---------- My Runs ----------
async function refreshMyRuns() {
  if (!__identity) return;
  const params = new URLSearchParams({ user_id: __identity.user_id });
  const search = $("runsSearch")?.value || "";
  const sec = $("runsFilterSector")?.value || "";
  const stg = $("runsFilterStage")?.value || "";
  const out = $("runsFilterOutcome")?.value || "";
  if (search) params.set("search", search);
  if (sec) params.set("sector", sec);
  if (stg) params.set("stage", stg);
  if (out) params.set("outcome", out);
  try {
    const res = await fetch(`/runs?${params.toString()}`, { cache: "no-store" });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const j = await res.json();
    renderMyRuns(j.runs || []);
  } catch (e) {
    console.error("runs list failed", e);
  }
}

const OUTCOME_LABELS = {
  unset: "Unset", advanced: "Advanced", passed: "Passed",
  invested: "Invested", declined: "Declined",
  built: "Built", pivoted: "Pivoted", killed: "Killed",
};

function renderMyRuns(rows) {
  const ul = $("myRunsList");
  ul.innerHTML = "";
  if (!rows.length) {
    ul.innerHTML = "<li class='hint'>No runs match these filters.</li>";
    return;
  }
  rows.forEach((r) => {
    const li = document.createElement("li");
    const score = r.final_score ?? "—";
    const badge = r.green_lit
      ? `<span class="rl-badge green">Green-lit</span>`
      : `<span class="rl-badge warn">Best draft</span>`;
    const oc = r.outcome || "unset";
    const ocLabel = OUTCOME_LABELS[oc] || oc;
    const tags = `
      <span class="rl-tag">${escapeHtml((r.sector || "other").replace(/_/g, " "))}</span>
      <span class="rl-tag">${escapeHtml((r.stage || "unspecified").replace(/_/g, " "))}</span>
      ${r.theme ? `<span class="rl-tag">${escapeHtml(r.theme)}</span>` : ""}
    `;
    li.innerHTML = `
      <span class="rl-date">${escapeHtml((r.started_at || "").slice(0, 10))}</span>
      <span class="rl-score">${score}</span>
      ${badge}
      <span class="rl-title">${escapeHtml(r.title || r.idea_preview || r.run_id)}</span>
      <span class="rl-tags">${tags}</span>
      <span class="rl-outcome ${oc}">${escapeHtml(ocLabel)}</span>
      <span class="rl-meta">${r.total_iterations || "—"} iter · $${(r.cost_usd || 0).toFixed(2)}</span>
      <span class="rl-actions">
        <a class="rl-btn" href="/runs/${encodeURIComponent(r.run_id)}/report.pdf" download>PDF</a>
        <button class="rl-btn" data-act="similar" data-run="${r.run_id}" title="Find semantically similar runs you own">Similar</button>
        <button class="rl-btn" data-act="outcome" data-run="${r.run_id}">Outcome</button>
        <button class="rl-btn danger" data-act="delete" data-run="${r.run_id}">Delete</button>
      </span>
    `;
    ul.appendChild(li);
  });
  ul.querySelectorAll("button[data-act='outcome']").forEach((b) =>
    b.addEventListener("click", () => openOutcomeDialog(b.dataset.run))
  );
  ul.querySelectorAll("button[data-act='delete']").forEach((b) =>
    b.addEventListener("click", () => deleteRun(b.dataset.run))
  );
}

async function deleteRun(runId) {
  if (!__identity) return;
  if (!confirm(`Delete run ${runId}? This permanently removes its files and analytics contribution.`)) return;
  try {
    const res = await fetch(`/runs/${encodeURIComponent(runId)}?user_id=${encodeURIComponent(__identity.user_id)}`, {
      method: "DELETE",
    });
    if (!res.ok) {
      const j = await res.json().catch(() => ({}));
      alert(`Delete failed: ${j.detail || res.status}`);
      return;
    }
    refreshMyRuns();
  } catch (e) {
    alert(`Delete error: ${e.message}`);
  }
}

function openOutcomeDialog(runId) {
  const oc = prompt(
    "Outcome — one of: advanced, passed, invested, declined, built, pivoted, killed, unset",
    "unset"
  );
  if (oc === null) return;
  const note = prompt("Note (optional):", "") || "";
  fetch(`/runs/${encodeURIComponent(runId)}/outcome?user_id=${encodeURIComponent(__identity.user_id)}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ outcome: oc.trim(), note: note.trim() }),
  }).then(async (res) => {
    if (!res.ok) {
      const j = await res.json().catch(() => ({}));
      alert(`Outcome update failed: ${j.detail || res.status}`);
      return;
    }
    refreshMyRuns();
  });
}

// ---------- Rubric ----------
async function refreshRubric() {
  if (!__identity) { openIdentityModal(); return; }
  const res = await fetch(`/rubric?user_id=${encodeURIComponent(__identity.user_id)}&persona=${encodeURIComponent(__identity.persona)}`);
  const j = await res.json();
  $("rubricPersonaTag").textContent = `· ${j.tunable ? "investor (tunable)" : __identity.persona + " (read-only)"}`;
  const w = j.weights || j.defaults;
  $("rubricMarket").value = w.market;
  $("rubricFeasibility").value = w.feasibility;
  $("rubricFounder").value = w.founder;
  const enabled = !!j.tunable;
  ["rubricMarket", "rubricFeasibility", "rubricFounder", "rubricSaveBtn", "rubricResetBtn"].forEach((id) => {
    const el = $(id); if (el) el.disabled = !enabled;
  });
  updateRubricUI();
  $("rubricStatus").textContent = enabled ? "" : "Only investor persona can tune.";
}

function updateRubricUI() {
  const m = +$("rubricMarket").value;
  const f = +$("rubricFeasibility").value;
  const fd = +$("rubricFounder").value;
  $("rubricMarketVal").textContent = `${m}%`;
  $("rubricFeasibilityVal").textContent = `${f}%`;
  $("rubricFounderVal").textContent = `${fd}%`;
  const total = m + f + fd;
  $("rubricTotal").textContent = `${total}%`;
  const warn = total < 95 || total > 105;
  $("rubricSumWarn").classList.toggle("hidden", !warn);
  $("rubricSaveBtn").disabled = warn;
}

["rubricMarket", "rubricFeasibility", "rubricFounder"].forEach((id) =>
  $(id)?.addEventListener("input", updateRubricUI)
);
$("rubricSaveBtn")?.addEventListener("click", async () => {
  if (!__identity) return;
  const weights = {
    market: +$("rubricMarket").value,
    feasibility: +$("rubricFeasibility").value,
    founder: +$("rubricFounder").value,
  };
  $("rubricSaveBtn").disabled = true;
  $("rubricStatus").textContent = "Saving…";
  try {
    const res = await fetch("/rubric", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_id: __identity.user_id, persona: __identity.persona, weights }),
    });
    if (!res.ok) {
      const j = await res.json().catch(() => ({}));
      throw new Error(j.detail || `HTTP ${res.status}`);
    }
    $("rubricStatus").textContent = "Saved. Applies on your next run.";
  } catch (e) {
    $("rubricStatus").textContent = `Failed: ${e.message}`;
  } finally {
    $("rubricSaveBtn").disabled = false;
  }
});
$("rubricResetBtn")?.addEventListener("click", () => {
  $("rubricMarket").value = 34;
  $("rubricFeasibility").value = 33;
  $("rubricFounder").value = 33;
  updateRubricUI();
});

// ---------- Priors transparency on user analytics ----------
const _origRenderUserAnalytics = renderUserAnalytics;
renderUserAnalytics = function patched(a) {
  _origRenderUserAnalytics(a);
  // Populate priors block from /analytics/flag-patterns
  fetch("/analytics/flag-patterns").then((r) => r.json()).then((p) => {
    const meta = p || {};
    $("uaPriorsMeta").textContent = meta.feedback_gate_active
      ? ` · ${meta.patterns?.length || 0} active · feedback gate ON`
      : ` · ${meta.patterns?.length || 0} active`;
    const list = $("uaPriorList");
    list.innerHTML = "";
    (p.patterns || []).slice(0, 8).forEach((pat) => {
      const li = document.createElement("li");
      li.innerHTML = `<strong>${escapeHtml(pat.title)}</strong> <span class="meta">[${escapeHtml(pat.section || "—")}] · ${pat.dominant_severity.toUpperCase()} · ${pat.run_count}/${meta.total_runs_considered || "?"} runs</span>`;
      list.appendChild(li);
    });
    if (!p.patterns || !p.patterns.length) {
      list.innerHTML = "<li class='hint'>No active priors yet. Run more reports to accumulate signal.</li>";
    }
  }).catch(() => {});
};

// ---------- Boot taxonomy ----------
(async function bootTaxonomy() {
  await fetchTaxonomy();
  populateTagDropdowns();
})();

// =============================================================================
// STOP RUN — cancel in-flight orchestrator and delete partial files
// =============================================================================
(function wireStopBtn() {
  const stopBtn = $("stopBtn");
  if (!stopBtn) return;
  stopBtn.addEventListener("click", async () => {
    if (!currentRunId) return;
    if (!confirm("Stop this run and delete its partial files? This cannot be undone.")) return;
    stopBtn.disabled = true;
    stopBtn.textContent = "Stopping…";
    try {
      const uid = __identity ? __identity.user_id : "";
      const res = await fetch(
        `/runs/${encodeURIComponent(currentRunId)}/stop?user_id=${encodeURIComponent(uid)}`,
        { method: "POST" }
      );
      if (!res.ok) {
        const j = await res.json().catch(() => ({}));
        setStatus(`Stop failed: ${j.detail || res.status}`, false);
        stopBtn.disabled = false;
        stopBtn.textContent = "⏹ Stop run";
        return;
      }
      // Close the SSE stream — server may have already.
      if (es) { es.close(); es = null; }
      if (reconnectTimer) { clearTimeout(reconnectTimer); reconnectTimer = null; }
      isReconnecting = false;
      setStatus("Stopped. Partial files deleted.", false);
      btn.disabled = false;
      btn.textContent = "Process this idea";
      stopBtn.classList.add("hidden");
      hidePausePanel();
      // Refresh the runs list if it's open.
      if (typeof refreshMyRuns === "function") refreshMyRuns();
    } catch (e) {
      setStatus(`Stop error: ${e.message}`, false);
      stopBtn.disabled = false;
      stopBtn.textContent = "⏹ Stop run";
    }
  });
})();

// =============================================================================
// ATTACHMENTS — file lives server-side; textarea is for user's own prompt
// =============================================================================
let __attachment = null;  // { attachment_id, filename, kind, pages, raw_chars, brief_chars, ... }

function setAttachment(data) {
  __attachment = data;
  const chip = $("attachmentChip");
  if (!chip) return;
  chip.classList.remove("hidden");
  $("acTitle").textContent = data.filename || data.attachment_id || "attached";
  const pageBit = data.pages ? `${data.pages} pages · ` : "";
  const rawKB = ((data.raw_chars ?? 0) / 1024).toFixed(1);
  const briefKB = ((data.brief_chars ?? 0) / 1024).toFixed(1);
  $("acMeta").textContent = `${pageBit}${rawKB} KB raw → ${briefKB} KB brief`;
  $("briefRevealDetails")?.classList.add("hidden");
  if ($("briefRevealDetails")) $("briefRevealDetails").open = false;
}

function clearAttachment() {
  __attachment = null;
  const chip = $("attachmentChip");
  if (chip) chip.classList.add("hidden");
  const rev = $("briefRevealDetails");
  if (rev) { rev.classList.add("hidden"); rev.open = false; }
  // Reset upload status so user sees clean state.
  if (uploadStatus) {
    uploadStatus.textContent = "";
    uploadStatus.classList.add("hidden");
    uploadStatus.classList.remove("success", "error");
  }
}

(function wireAttachmentChip() {
  const viewBtn = $("acViewBriefBtn");
  const removeBtn = $("acRemoveBtn");
  const reveal = $("briefRevealDetails");
  const revealPre = $("briefRevealPre");
  if (viewBtn) {
    viewBtn.addEventListener("click", async () => {
      if (!__attachment) return;
      try {
        const res = await fetch(`/attachments/${encodeURIComponent(__attachment.attachment_id)}/brief`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const j = await res.json();
        // Use marked if available, else raw text.
        if (window.marked) {
          revealPre.innerHTML = window.marked.parse(j.brief || "");
        } else {
          revealPre.textContent = j.brief || "";
        }
        reveal.classList.remove("hidden");
        reveal.open = true;
        reveal.scrollIntoView({ behavior: "smooth", block: "nearest" });
      } catch (e) {
        alert(`Could not load brief: ${e.message}`);
      }
    });
  }
  if (removeBtn) {
    removeBtn.addEventListener("click", async () => {
      if (!__attachment) return;
      const aid = __attachment.attachment_id;
      clearAttachment();
      // Fire-and-forget server cleanup; UI is already updated.
      fetch(`/attachments/${encodeURIComponent(aid)}`, { method: "DELETE" }).catch(() => {});
    });
  }
})();

// Patch startRun to attach `attachment_id` instead of `raw_source`.
const _origStartRun = startRun;
startRun = function patchedStartRun(body) {
  if (__attachment && __attachment.attachment_id) {
    body.attachment_id = __attachment.attachment_id;
  }
  return _origStartRun(body);
};

// When the textarea is empty AND no attachment, disable the Process button.
// (Server validates this too; doing it client-side gives faster feedback.)
function refreshProcessBtnEnabled() {
  if (!btn) return;
  const hasText = (ideaEl.value || "").trim().length > 0;
  const hasAttachment = !!(__attachment && __attachment.attachment_id);
  // We only disable when both are empty AND the run hasn't started.
  if (btn.textContent === "Processing…") return;
  btn.disabled = !(hasText || hasAttachment);
}
ideaEl?.addEventListener("input", refreshProcessBtnEnabled);
// Initial state.
refreshProcessBtnEnabled();
// Hook so chip add/remove also updates button state.
const _origSetAttachment = setAttachment;
setAttachment = function patchedSetAttachment(d) { _origSetAttachment(d); refreshProcessBtnEnabled(); };
const _origClearAttachment = clearAttachment;
clearAttachment = function patchedClearAttachment() { _origClearAttachment(); refreshProcessBtnEnabled(); };

// =============================================================================
// REFINE — post-loop multi-turn chat over the final BRD
// =============================================================================
(function wireRefine() {
  const panel = $("refinePanel");
  const thread = $("refineThread");
  const input = $("refineInput");
  const send = $("refineSendBtn");
  const status = $("refineStatus");
  if (!panel || !send) return;

  function setStatus(msg, kind) {
    status.textContent = msg || "";
    status.classList.remove("error");
    if (kind === "error") status.classList.add("error");
  }

  function renderTurn(turn) {
    const div = document.createElement("div");
    div.className = `refine-turn ${turn.role}`;
    const who = turn.role === "user" ? (__identity?.user_id || "you") : "assistant";
    const bodyHtml = (turn.role === "assistant" && window.marked)
      ? window.marked.parse(turn.content || "")
      : escapeHtml(turn.content || "").replaceAll("\n", "<br>");
    div.innerHTML = `<div class="who">${escapeHtml(who)}</div><div class="body">${bodyHtml}</div>`;
    thread.appendChild(div);
    thread.scrollTop = thread.scrollHeight;
  }

  async function loadHistory() {
    if (!currentRunId) return;
    try {
      const res = await fetch(`/runs/${encodeURIComponent(currentRunId)}/refine?user_id=${encodeURIComponent(__identity?.user_id || "")}`);
      if (!res.ok) return;
      const j = await res.json();
      thread.innerHTML = "";
      (j.thread || []).forEach(renderTurn);
    } catch (e) { /* ignore */ }
  }

  async function sendMessage() {
    if (!currentRunId) {
      setStatus("No active run to refine.", "error");
      return;
    }
    const message = (input.value || "").trim();
    if (!message) return;
    send.disabled = true;
    input.disabled = true;
    setStatus("Thinking…");
    renderTurn({ role: "user", content: message });
    input.value = "";
    try {
      const res = await fetch(`/runs/${encodeURIComponent(currentRunId)}/refine?user_id=${encodeURIComponent(__identity?.user_id || "")}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message }),
      });
      if (!res.ok) {
        const j = await res.json().catch(() => ({}));
        throw new Error(j.detail || `HTTP ${res.status}`);
      }
      const j = await res.json();
      renderTurn(j.assistant);
      setStatus("");
    } catch (e) {
      setStatus(`Failed: ${e.message}`, "error");
    } finally {
      send.disabled = false;
      input.disabled = false;
      input.focus();
    }
  }

  send.addEventListener("click", sendMessage);
  input.addEventListener("keydown", (e) => {
    if ((e.metaKey || e.ctrlKey) && e.key === "Enter") sendMessage();
  });

  // Expose for the final-event handler to call.
  window.__showRefinePanel = () => {
    panel.classList.remove("hidden");
    thread.innerHTML = "";
    input.value = "";
    setStatus("");
    loadHistory();
  };
  window.__hideRefinePanel = () => panel.classList.add("hidden");
})();

// =============================================================================
// ADMIN — backfill embeddings
// =============================================================================
(function wireBackfill() {
  const btn = $("adminBackfillEmbedBtn");
  const status = $("adminBackfillStatus");
  if (!btn) return;
  btn.addEventListener("click", async () => {
    if (!__identity) return;
    btn.disabled = true;
    status.textContent = "Embedding…";
    try {
      const res = await fetch(`/runs/_backfill_embeddings?user_id=${encodeURIComponent(__identity.user_id)}&limit=50`, {
        method: "POST",
      });
      if (!res.ok) {
        const j = await res.json().catch(() => ({}));
        throw new Error(j.detail || `HTTP ${res.status}`);
      }
      const j = await res.json();
      status.textContent = `Embedded ${j.embedded} of ${j.considered} candidate runs (${j.failed} failed).`;
    } catch (e) {
      status.textContent = `Failed: ${e.message}`;
    } finally {
      btn.disabled = false;
    }
  });
})();

// =============================================================================
// MY RUNS — similar-runs reveal per row
// =============================================================================
(function wireSimilarRunsButtons() {
  // The row markup is rendered by renderMyRuns; intercept via event delegation.
  const list = $("myRunsList");
  if (!list) return;
  list.addEventListener("click", async (e) => {
    const btn = e.target.closest("button[data-act='similar']");
    if (!btn) return;
    e.preventDefault();
    const runId = btn.dataset.run;
    if (!runId) return;
    btn.disabled = true;
    btn.textContent = "Loading…";
    try {
      const uid = __identity ? __identity.user_id : "";
      const res = await fetch(`/runs/${encodeURIComponent(runId)}/similar?user_id=${encodeURIComponent(uid)}&top_k=5`);
      if (!res.ok) {
        const j = await res.json().catch(() => ({}));
        throw new Error(j.detail || `HTTP ${res.status}`);
      }
      const j = await res.json();
      // Insert a sibling row showing the matches.
      const host = btn.closest("li");
      let panel = host.nextElementSibling;
      if (!panel || !panel.classList.contains("similar-panel")) {
        panel = document.createElement("li");
        panel.className = "similar-panel";
        host.parentNode.insertBefore(panel, host.nextSibling);
      }
      if (!j.matches.length) {
        panel.innerHTML = `<div class="hint">No semantically similar runs found yet. ${j.reason || ""}</div>`;
      } else {
        panel.innerHTML = `<div class="hint">Similar runs (by final-BRD embedding):</div>` +
          j.matches.map((m) =>
            `<div class="similar-row">
              <span class="rl-date">${escapeHtml((m.started_at || "").slice(0,10))}</span>
              <span class="rl-score">${m.final_score ?? "—"}</span>
              <span class="rl-title">${escapeHtml(m.title || m.idea_preview || m.run_id)}</span>
              <span class="rl-meta">sim ${m.similarity.toFixed(3)} · ${escapeHtml(m.outcome || "unset")}</span>
            </div>`
          ).join("");
      }
    } catch (err) {
      alert(`Similar runs failed: ${err.message}`);
    } finally {
      btn.disabled = false;
      btn.textContent = "Similar";
    }
  });
})();

// =============================================================================
// FEEDBACK ANALYSIS — admin product-insights view
// =============================================================================
(function wireFeedbackAnalysis() {
  const btn = $("faAnalyzeBtn");
  const status = $("faStatusLine");
  const body = $("faBody");
  if (!btn) return;

  async function uid() {
    return __identity ? encodeURIComponent(__identity.user_id) : "";
  }

  async function loadStatus() {
    if (!__identity) { status.textContent = "Identity required."; return; }
    try {
      const [stRes, anRes] = await Promise.all([
        fetch(`/admin/feedback/status?user_id=${await uid()}`),
        fetch(`/admin/feedback/analyze?user_id=${await uid()}`),
      ]);
      if (stRes.status === 403) {
        status.textContent = "Admin only.";
        btn.disabled = true;
        return;
      }
      const st = await stRes.json();
      const an = await anRes.json();
      renderStatusLine(st, an?.cached);
      btn.disabled = !st.ready;
      btn.textContent = an?.cached ? "Re-analyze" : "Analyze";
      if (an?.cached) renderAnalysis(an.cached);
      else body.classList.add("hidden");
    } catch (e) {
      status.textContent = `Failed to load status: ${e.message}`;
    }
  }

  function renderStatusLine(st, cached) {
    const parts = [];
    parts.push(`${st.feedback_count} feedback record${st.feedback_count === 1 ? "" : "s"}`);
    if (!st.ready) {
      parts.push(`need ${st.min_required - st.feedback_count} more to analyze`);
    } else if (cached) {
      const when = cached.generated_at ? cached.generated_at.slice(0, 19) + "Z" : "unknown";
      parts.push(`last analyzed ${when} on ${cached.feedback_count_at_analysis} records`);
      if (st.stale) parts.push(`${st.new_since_cache} new since — re-analyze recommended`);
    } else {
      parts.push("ready to analyze");
    }
    status.textContent = parts.join(" · ");
  }

  async function runAnalysis() {
    if (!__identity) return;
    btn.disabled = true;
    const prevText = btn.textContent;
    btn.textContent = "Analyzing… 10-20s";
    try {
      const res = await fetch(`/admin/feedback/analyze?user_id=${await uid()}`, { method: "POST" });
      if (!res.ok) {
        const j = await res.json().catch(() => ({}));
        throw new Error(j.detail || `HTTP ${res.status}`);
      }
      const payload = await res.json();
      renderAnalysis(payload);
      await loadStatus();  // refresh status line + button text
    } catch (e) {
      status.textContent = `Analysis failed: ${e.message}`;
      btn.disabled = false;
      btn.textContent = prevText;
    }
  }

  function renderAnalysis(payload) {
    body.classList.remove("hidden");
    const a = payload.analysis || {};
    $("faMeta").textContent =
      `Generated ${(payload.generated_at || "").slice(0, 19)}Z · model ${payload.model} · cost $${(payload.cost_usd || 0).toFixed(4)} · ${payload.feedback_count_at_analysis} records`;
    $("faSummary").textContent = a.summary || "—";

    // Sentiment pills
    const s = a.sentiment || {};
    const overall = (s.overall || "").toLowerCase();
    $("faSentiment").innerHTML = `
      <div class="pill up"><span class="v">${s.up || 0}</span><span class="k">👍 Useful</span></div>
      <div class="pill down"><span class="v">${s.down || 0}</span><span class="k">👎 Off-base</span></div>
      <div class="pill acted"><span class="v">${s.acted_on || 0}</span><span class="k">✅ Acted on</span></div>
      <div class="pill"><span class="v">${escapeHtml(overall || "—")}</span><span class="k">Overall</span></div>
    `;

    // Themes
    const themes = $("faThemes");
    themes.innerHTML = (a.themes || []).map((t) => `
      <li>
        <span class="fa-name">${escapeHtml(t.name)}</span>
        <span class="fa-meta-small">frequency ${t.frequency || (t.example_run_ids||[]).length} · ${(t.example_run_ids||[]).length} run${(t.example_run_ids||[]).length===1?"":"s"}</span>
        ${t.representative_note ? `<span class="fa-quote">${escapeHtml(t.representative_note)}</span>` : ""}
      </li>
    `).join("") || "<li class='hint'>No recurring themes detected yet.</li>";

    // Complaints
    const comps = $("faComplaints");
    comps.innerHTML = (a.complaints || []).map((c) => `
      <li>
        <span class="fa-name">${escapeHtml(c.issue)}</span>
        <span class="fa-meta-small">confidence: ${escapeHtml(c.confidence || "—")} · ${(c.evidence_run_ids||[]).length} run${(c.evidence_run_ids||[]).length===1?"":"s"}</span>
        ${(c.example_quotes || []).slice(0, 2).map(q => `<span class="fa-quote">${escapeHtml(q)}</span>`).join("")}
      </li>
    `).join("") || "<li class='hint'>No complaints surfaced.</li>";

    // Praises
    const pra = $("faPraises");
    pra.innerHTML = (a.praises || []).map((p) => `
      <li>
        <span class="fa-name">${escapeHtml(p.strength)}</span>
        <span class="fa-meta-small">${(p.evidence_run_ids||[]).length} run${(p.evidence_run_ids||[]).length===1?"":"s"}</span>
        ${(p.example_quotes || []).slice(0, 2).map(q => `<span class="fa-quote">${escapeHtml(q)}</span>`).join("")}
      </li>
    `).join("") || "<li class='hint'>No clear praises surfaced.</li>";

    // Recommended actions
    const act = $("faActions");
    act.innerHTML = (a.recommended_actions || []).map((r) => {
      const effort = (r.effort || "medium").toLowerCase();
      return `
        <li>
          <span class="fa-action-tag effort-${effort}">${escapeHtml(effort)}</span>
          ${r.risk ? `<span class="fa-action-tag risk">risk: ${escapeHtml(r.risk).slice(0, 60)}</span>` : ""}
          <span class="fa-name">${escapeHtml(r.action)}</span>
          <span class="fa-meta-small">${escapeHtml(r.rationale || "")}</span>
        </li>
      `;
    }).join("") || "<li class='hint'>No action recommendations.</li>";
  }

  btn.addEventListener("click", runAnalysis);

  // Patch into refreshAnalytics so this loads when admin tab opens
  const _origRefresh = refreshAnalytics;
  refreshAnalytics = async function patched() {
    await _origRefresh();
    await loadStatus();
  };
})();

// =============================================================================
// NEW IDEA — clear everything and return to the intake form
// =============================================================================
(function wireNewIdea() {
  const newBtn = $("newIdeaBtn");
  if (!newBtn) return;

  newBtn.addEventListener("click", () => {
    // Close any open SSE so the next run starts clean.
    if (es) { try { es.close(); } catch {} es = null; }
    if (reconnectTimer) { clearTimeout(reconnectTimer); reconnectTimer = null; }
    isReconnecting = false;
    reconnectAttempt = 0;
    runTerminated = false;
    currentRunId = null;

    // Clear in-flight UI state.
    for (const k of Object.keys(iterCards)) delete iterCards[k];
    itersEl.innerHTML = "";
    if (typeof hidePausePanel === "function") hidePausePanel();

    // Clear final-report panels.
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
    if (typeof window.__hideFeedback === "function") window.__hideFeedback();
    if (typeof window.__hideRefinePanel === "function") window.__hideRefinePanel();

    // Hide the run panel + reset status.
    runEl.classList.add("hidden");
    setStatus("", false);

    // Reset Process button.
    btn.disabled = false;
    btn.textContent = "Process this idea";

    // Clear intake fields.
    ideaEl.value = "";
    ideaEl.dispatchEvent(new Event("input"));
    if (uploadStatus) {
      uploadStatus.textContent = "";
      uploadStatus.classList.add("hidden");
      uploadStatus.classList.remove("success", "error");
    }
    if (typeof clearAttachment === "function") clearAttachment();

    // Show intake, scroll to it, focus the idea textarea.
    const intake = $("intake");
    if (intake) intake.classList.remove("hidden");
    // Force the New-run tab to be visible/active so the user lands in the right place.
    document.querySelectorAll(".tabs .tab").forEach((t) =>
      t.classList.toggle("active", t.dataset.tab === "run")
    );
    ["myRunsPanel", "userAnalyticsPanel", "rubricPanel", "analyticsPanel"].forEach((id) => {
      const el = $(id); if (el) el.classList.add("hidden");
    });
    if (intake) intake.scrollIntoView({ behavior: "smooth", block: "start" });
    ideaEl.focus();
  });
})();
