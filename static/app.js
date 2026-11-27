// ===== 投稿ポップアップ =====
const modal = document.getElementById("postModal");
document.getElementById("openPost")?.addEventListener("click", () => {
  modal.hidden = false;
  modal.querySelector("input[name=title]").focus();
});
document.getElementById("closePost")?.addEventListener("click", () => (modal.hidden = true));
modal?.addEventListener("click", (e) => { if (e.target === modal) modal.hidden = true; });
document.addEventListener("keydown", (e) => { if (e.key === "Escape" && modal) modal.hidden = true; });

// ===== マイページのタブ切り替え =====
document.querySelectorAll(".tabs[data-switch] a").forEach((tab) => {
  tab.addEventListener("click", (e) => {
    e.preventDefault();
    document.querySelectorAll(".tabs[data-switch] a").forEach((t) => t.classList.toggle("active", t === tab));
    document.querySelectorAll(".pane").forEach((p) => (p.hidden = "#" + p.id !== tab.getAttribute("href")));
  });
});

// ===== ドーパミン音（音声ファイルなしで、ブラウザで音を作る） =====
let audioCtx;
function playDopamine(combo) {
  audioCtx ??= new (window.AudioContext || window.webkitAudioContext)();
  const now = audioCtx.currentTime;
  // 連打するほど音が高くなる
  const base = 523 * Math.pow(2, Math.min(combo, 12) / 12);
  [0, 4, 7, 12].forEach((step, i) => {
    const osc = audioCtx.createOscillator();
    const gain = audioCtx.createGain();
    osc.type = i === 3 ? "sine" : "square";
    osc.frequency.value = base * Math.pow(2, step / 12);
    const t = now + i * 0.06;
    gain.gain.setValueAtTime(0.0001, t);
    gain.gain.exponentialRampToValueAtTime(0.15, t + 0.01);
    gain.gain.exponentialRampToValueAtTime(0.0001, t + 0.25);
    osc.connect(gain).connect(audioCtx.destination);
    osc.start(t);
    osc.stop(t + 0.3);
  });
}

function playUndo() {
  audioCtx ??= new (window.AudioContext || window.webkitAudioContext)();
  const osc = audioCtx.createOscillator();
  const gain = audioCtx.createGain();
  const now = audioCtx.currentTime;
  osc.frequency.setValueAtTime(400, now);
  osc.frequency.exponentialRampToValueAtTime(150, now + 0.2);
  gain.gain.setValueAtTime(0.1, now);
  gain.gain.exponentialRampToValueAtTime(0.0001, now + 0.2);
  osc.connect(gain).connect(audioCtx.destination);
  osc.start(now);
  osc.stop(now + 0.22);
}

// ===== ドーパミンの演出 =====
const SPARKS = ["🧠", "⚡", "🔥", "💥", "✨", "💉"];
const WORDS = ["ドーパミン!!", "脳汁ドバー!!", "激熱!!", "キタ━━!!", "+1 DOPAMINE"];
function burst(btn) {
  const r = btn.getBoundingClientRect();
  const cx = r.left + r.width / 2, cy = r.top + r.height / 2;
  for (let i = 0; i < 14; i++) {
    const s = document.createElement("span");
    s.className = "spark";
    s.textContent = SPARKS[i % SPARKS.length];
    const angle = Math.random() * Math.PI * 2, dist = 60 + Math.random() * 90;
    s.style.left = cx + "px";
    s.style.top = cy + "px";
    s.style.setProperty("--dx", Math.cos(angle) * dist + "px");
    s.style.setProperty("--dy", Math.sin(angle) * dist + "px");
    s.style.setProperty("--rot", (Math.random() * 720 - 360) + "deg");
    document.body.appendChild(s);
    setTimeout(() => s.remove(), 950);
  }
  const pop = document.createElement("div");
  pop.className = "dopa-pop";
  pop.textContent = WORDS[Math.floor(Math.random() * WORDS.length)];
  pop.style.left = cx + "px";
  pop.style.top = r.top - 10 + "px";
  document.body.appendChild(pop);
  setTimeout(() => pop.remove(), 950);

  document.body.classList.remove("flash-screen");
  void document.body.offsetWidth;
  document.body.classList.add("flash-screen");
  navigator.vibrate?.(40);
}

// ===== ドーパミンボタン =====
let combo = 0, comboTimer;
document.addEventListener("click", async (e) => {
  const btn = e.target.closest(".dopa");
  if (!btn) return;
  if (!window.LOGGED_IN) { location.href = "/login?next=" + encodeURIComponent(location.pathname); return; }
  if (btn.disabled) return;
  btn.disabled = true;
  try {
    const res = await fetch(`/api/post/${btn.dataset.id}/dopamine`, { method: "POST" });
    if (!res.ok) throw new Error(res.status);
    const data = await res.json();
    btn.querySelector(".count").textContent = data.dopamine;
    btn.classList.toggle("on", data.liked);
    if (data.liked) {
      clearTimeout(comboTimer);
      combo++;
      comboTimer = setTimeout(() => (combo = 0), 3000);
      playDopamine(combo);
      burst(btn);
      btn.classList.remove("boom");
      void btn.offsetWidth;
      btn.classList.add("boom");
    } else {
      playUndo();
    }
  } catch (err) {
    alert("ドーパミンを送れなかった…もう一回試してね");
  } finally {
    btn.disabled = false;
  }
});
