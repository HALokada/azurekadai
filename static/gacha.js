// ===== ドーパミンガチャ =====
const drawBtn = document.getElementById("drawBtn");
const capsule = document.getElementById("capsule");
const resultModal = document.getElementById("resultModal");

// ドラムロールの音
function drumRoll(seconds) {
  const ctx = new (window.AudioContext || window.webkitAudioContext)();
  const now = ctx.currentTime;
  for (let t = 0; t < seconds; t += 0.06) {
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.type = "triangle";
    osc.frequency.value = 120 + t * 80;
    gain.gain.setValueAtTime(0.08, now + t);
    gain.gain.exponentialRampToValueAtTime(0.0001, now + t + 0.05);
    osc.connect(gain).connect(ctx.destination);
    osc.start(now + t);
    osc.stop(now + t + 0.06);
  }
  return ctx;
}

// 当たりの音（レアほど長く華やか）
function fanfare(ctx, rarity) {
  const steps = { N: [0, 7], R: [0, 4, 7], SR: [0, 4, 7, 12], SSR: [0, 4, 7, 12, 16, 19], UR: [0, 4, 7, 12, 16, 19, 24, 28, 31] }[rarity];
  const now = ctx.currentTime;
  steps.forEach((s, i) => {
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.type = "square";
    osc.frequency.value = 392 * Math.pow(2, s / 12);
    const t = now + i * 0.09;
    gain.gain.setValueAtTime(0.0001, t);
    gain.gain.exponentialRampToValueAtTime(0.12, t + 0.01);
    gain.gain.exponentialRampToValueAtTime(0.0001, t + 0.4);
    osc.connect(gain).connect(ctx.destination);
    osc.start(t);
    osc.stop(t + 0.45);
  });
}

drawBtn?.addEventListener("click", async () => {
  drawBtn.disabled = true;
  capsule.classList.add("shake");
  const ctx = drumRoll(1.8);
  let data;
  try {
    const res = await fetch("/api/gacha", { method: "POST" });
    data = await res.json();
    if (!res.ok) throw new Error(data.error || "エラー");
  } catch (err) {
    capsule.classList.remove("shake");
    alert(err.message);
    return;
  }
  setTimeout(() => {
    capsule.classList.remove("shake");
    capsule.classList.add("open");
    fanfare(ctx, data.rarity);

    const rare = ["SSR", "UR"].includes(data.rarity);
    rain(rare ? 80 : data.rarity === "SR" ? 40 : 15, rare ? ["🌈", "✨", "👑", "💎", "🧠"] : ["✨", "🎉", "🧠"]);
    if (rare) document.body.classList.add("jackpot");

    document.getElementById("resultRarity").textContent = data.rarity;
    document.getElementById("resultRarity").className = "rar big-rar rar-" + data.rarity;
    document.getElementById("resultName").textContent = data.name + " GET!!";
    document.getElementById("resultNote").textContent = data.duplicate
      ? "かぶっちゃった…でも明日また引ける！"
      : (data.kind === "frame" ? "アイコンの枠だよ。コレクションから装備できる！" : "ドーパミンボタンの色だよ。コレクションから装備できる！");
    const preview = document.getElementById("resultPreview");
    preview.innerHTML = "";
    if (data.kind === "frame") {
      const a = document.createElement("span");
      a.className = "avatar big " + data.id;
      a.textContent = window.ME_INITIAL;
      preview.appendChild(a);
    } else {
      const wrap = document.createElement("span");
      wrap.className = "pv " + data.id;
      wrap.innerHTML = '<span class="dopa on">🧠 99 ドーパミン</span>';
      preview.appendChild(wrap);
    }
    document.getElementById("resultBox").className = "modal-box notice result result-" + data.rarity;
    resultModal.hidden = false;
    drawBtn.textContent = "今日はもう引いたよ（また明日）";
  }, 1800);
});
