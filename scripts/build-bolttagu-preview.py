"""Generate a self-contained page for choosing which animation means what.

The page plays every bundled pose from the atlases the overlay actually draws --
not the raw sprite pack -- so what you pick is what you get. Choosing a mapping
writes no code: the page exports the JSON that ``load_mapping`` reads from
``~/.engram/overlays/bolttagu-2d/mapping.json``.

Clip timings, the pose roster and the built-in defaults all come from
``bolttagu_2d`` so the page cannot drift from the renderer.

Usage:
    python scripts/build-bolttagu-preview.py
    python scripts/build-bolttagu-preview.py --open
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
import webbrowser
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from engram_overlay.overlays.bolttagu_2d import (  # noqa: E402
    ASSET_DIR,
    BLINK_INTERVAL_MS,
    BLINK_SEQUENCE,
    CATEGORY_POSES,
    CLIPS,
    EYE_CELLS,
    HINT_ONESHOTS,
    IDLE_POSE,
    MAPPING_FILE,
    REFINABLE_CATEGORIES,
    STATE_POSES,
    STEAM_CELLS,
    STEAM_FRAME_MS,
    installed_mapping_path,
    selectable_oneshots,
    selectable_poses,
)

OUTPUT = REPO_ROOT / "dist" / "bolttagu-mapping.html"

# Engram's hints, in the order a turn actually moves through them.
HINT_ORDER = (
    "idle", "default", "input", "generating", "thought",
    "search", "memory", "success", "hover", "click", "error", "provider_error",
)
HINT_NOTES = {
    "idle": "유휴",
    "default": "기본",
    "input": "사용자 입력 제출",
    "generating": "응답 생성 · 도구 실행",
    "thought": "생각 중",
    "search": "검색 도구",
    "memory": "기억 도구",
    "success": "턴 완료",
    "hover": "포인터 올림",
    "click": "클릭",
    "error": "도구 실패",
    "provider_error": "provider 실패",
}
CATEGORY_NOTES = {
    "write": "write · edit · patch · delete",
    "execute": "shell · exec · build · test · run",
    "read": "read · open",
    "memory": "memory · kg_ · recall",
    "search": "search · find · web · grep",
    "communication": "mail · message · discord",
    "other": "그 외",
}


def data_uri(path: Path) -> str:
    return "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode("ascii")


def build_payload() -> dict[str, object]:
    metadata = json.loads((ASSET_DIR / "atlas.json").read_text(encoding="utf-8"))
    sheets: dict[str, dict[str, object]] = {}
    for file_name, frames in metadata["sheets"].items():
        key = Path(file_name).stem.removeprefix("bolttagu-")
        sheets[key] = {"src": data_uri(ASSET_DIR / file_name), "count": len(frames)}
    return {
        "cell": metadata["cell"],
        "source": metadata["source"],
        "sheets": sheets,
        "clips": {
            name: {"sheet": clip.sheet, "durations": list(clip.durations_ms), "loop": clip.loop}
            for name, clip in CLIPS.items()
        },
        "idle": {
            "pose": IDLE_POSE,
            "eyeCells": EYE_CELLS,
            "blink": [list(step) for step in BLINK_SEQUENCE],
            "blinkInterval": list(BLINK_INTERVAL_MS),
            "steamCells": STEAM_CELLS,
            "steamFrameMs": STEAM_FRAME_MS,
        },
        "poses": selectable_poses(),
        "oneshots": selectable_oneshots(),
        "hints": [
            {
                "key": key,
                "note": HINT_NOTES.get(key, ""),
                "default": STATE_POSES[key],
                "defaultOneshot": HINT_ONESHOTS.get(key, ""),
            }
            for key in HINT_ORDER
        ],
        "categories": [
            {
                "key": key,
                "note": CATEGORY_NOTES.get(key, ""),
                "default": CATEGORY_POSES.get(key, ""),
            }
            for key in ("write", "execute", "read", "communication", "other")
            if key in REFINABLE_CATEGORIES
        ],
        "mappingPath": str(installed_mapping_path()),
        "mappingFile": MAPPING_FILE,
    }


TEMPLATE = """<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Bolttagu 매핑</title>
<style>
  :root {
    --ground:#f4f6f8; --surface:#fff; --sunken:#e9edf1; --ink:#161b21; --ink-soft:#414d5a;
    --muted:#6d7a88; --rule:#d5dce3; --accent:#1f5f8b; --accent-soft:#e2eef6; --ok:#2f6b4f;
    --sans:"Segoe UI",system-ui,-apple-system,sans-serif;
    --mono:"Cascadia Mono",Consolas,ui-monospace,monospace;
  }
  @media (prefers-color-scheme:dark){:root{
    --ground:#0f1419; --surface:#171d24; --sunken:#1e262f; --ink:#e6ebf0; --ink-soft:#b3bec9;
    --muted:#8794a2; --rule:#2b333d; --accent:#78b0d6; --accent-soft:#16303f; --ok:#7cc7a0;
  }}
  *{box-sizing:border-box}
  body{margin:0;background:var(--ground);color:var(--ink);font-family:var(--sans);line-height:1.65}
  .page{max-width:1180px;margin:0 auto;padding:2.5rem 1.25rem 5rem}
  h1{font-size:1.7rem;margin:0 0 .35rem;letter-spacing:-.01em}
  .sub{color:var(--ink-soft);margin:0 0 .4rem;max-width:70ch}
  .prov{font-family:var(--mono);font-size:.75rem;color:var(--muted);margin:0 0 2.25rem}
  h2{font-size:.78rem;font-family:var(--mono);letter-spacing:.14em;text-transform:uppercase;
     color:var(--muted);font-weight:600;display:flex;align-items:center;gap:1rem;margin:2.75rem 0 1.1rem}
  h2::after{content:"";flex:1;height:1px;background:var(--rule)}

  .poses{display:grid;grid-template-columns:repeat(auto-fill,minmax(132px,1fr));gap:.9rem}
  .pose{background:var(--surface);border:1px solid var(--rule);border-radius:4px;padding:.55rem;text-align:center}
  .pose canvas{width:100%;height:auto;display:block;image-rendering:auto}
  .pose .name{font-family:var(--mono);font-size:.76rem;margin-top:.4rem;color:var(--ink)}
  .pose .ms{font-family:var(--mono);font-size:.66rem;color:var(--muted)}
  .pose.oneshot{opacity:.85;border-style:dashed}

  table{width:100%;border-collapse:collapse;font-size:.9rem}
  th,td{text-align:left;padding:.5rem .6rem;border-bottom:1px solid var(--rule);vertical-align:middle}
  thead th{font-family:var(--mono);font-size:.68rem;letter-spacing:.1em;text-transform:uppercase;
           color:var(--muted);font-weight:600}
  td.key{font-family:var(--mono);white-space:nowrap}
  td.note{color:var(--muted);font-size:.84rem}
  td.thumb{width:64px}
  td.thumb canvas{width:56px;height:auto;display:block;background:var(--sunken);border-radius:3px}
  select{font-family:var(--mono);font-size:.85rem;padding:.28rem .4rem;background:var(--surface);
         color:var(--ink);border:1px solid var(--rule);border-radius:3px;min-width:9.5rem}
  select:focus-visible{outline:2px solid var(--accent);outline-offset:1px}
  tr.changed td.key{color:var(--accent);font-weight:600}
  tr.changed td.key::after{content:" ●";color:var(--accent)}

  .bar{display:flex;flex-wrap:wrap;gap:.6rem;align-items:center;margin:1.25rem 0 .9rem}
  button{font-family:var(--sans);font-size:.88rem;padding:.45rem .9rem;border-radius:3px;
         border:1px solid var(--rule);background:var(--surface);color:var(--ink);cursor:pointer}
  button.primary{background:var(--accent);border-color:var(--accent);color:#fff}
  button:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
  .said{color:var(--ok);font-size:.85rem;font-family:var(--mono)}
  textarea{width:100%;min-height:11rem;font-family:var(--mono);font-size:.8rem;line-height:1.55;
           background:var(--sunken);color:var(--ink-soft);border:1px solid var(--rule);
           border-radius:4px;padding:.8rem;resize:vertical}
  code{font-family:var(--mono);background:var(--sunken);padding:.1em .35em;border-radius:2px;font-size:.88em}
  .path{font-family:var(--mono);font-size:.8rem;color:var(--ink-soft);word-break:break-all;
        background:var(--accent-soft);padding:.6rem .75rem;border-radius:3px;margin:.4rem 0 0}
  .hint{color:var(--muted);font-size:.85rem;margin:.5rem 0 0;max-width:74ch}
</style>
</head>
<body>
<div class="page">
  <h1>Bolttagu 매핑</h1>
  <p class="sub">각 신호에 어떤 동작을 붙일지 고른다. 아래 미리보기는 오버레이가 실제로 그리는 패킹된 셀을 같은 타이밍으로 재생한다.</p>
  <p class="prov" id="prov"></p>

  <h2>동작</h2>
  <div class="poses" id="poses"></div>
  <p class="hint">점선 테두리는 한 번만 재생되는 동작이다. 지속 동작으로 고르면 재생 후 마지막 프레임에서 멈춘다. <code>enter</code>·<code>exit</code>는 런처가 등장·퇴장에도 쓰지만, 그 전환은 1회 재생이라 항상 우선하므로 신호에 붙여도 충돌하지 않는다.</p>

  <h2>display hint</h2>
  <p class="hint" style="margin:-.5rem 0 1rem">신호마다 두 층이 있다. <b>지속 동작</b>은 그 상태에 머무는 동안 반복되고, <b>1회 재생</b>은 신호에 진입할 때 그 위로 한 번 얹힌 뒤 지속 동작으로 가라앉는다.</p>
  <table>
    <thead><tr><th>신호</th><th>의미</th><th>지속 동작</th><th></th><th>1회 재생</th><th></th></tr></thead>
    <tbody id="hints"></tbody>
  </table>

  <h2>도구 범주 — generating 세분</h2>
  <p class="hint" style="margin:-.5rem 0 1rem">Engram은 검색·기억이 아닌 모든 도구를 <code>generating</code>으로 뭉쳐 보내고, 어떤 일인지는 <code>payload.category</code>에만 담긴다. 아래에서 지정하지 않은 범주는 위 <code>generating</code> 설정을 그대로 쓴다.<br>
  <b>검색·기억 도구는 여기 없다.</b> 그 둘은 <code>generating</code>이 아니라 <code>search</code>·<code>memory</code> 신호로 직접 오므로 위 display hint 표에서 정한다.</p>
  <table>
    <thead><tr><th>범주</th><th>도구</th><th>동작</th><th></th></tr></thead>
    <tbody id="cats"></tbody>
  </table>

  <h2>적용</h2>
  <div class="bar">
    <button class="primary" id="copy">JSON 복사</button>
    <button id="download">파일로 저장</button>
    <button id="reset">기본값으로</button>
    <span class="said" id="said"></span>
  </div>
  <textarea id="out" readonly spellcheck="false"></textarea>
  <p class="hint">이 파일을 아래 경로에 두고 오버레이를 재시작한다. 기본값과 같은 항목은 쓰지 않는다.</p>
  <p class="path" id="path"></p>
</div>

<script id="payload" type="application/json">__PAYLOAD__</script>
<script>
const D = JSON.parse(document.getElementById("payload").textContent);
const [CW, CH] = D.cell;
const images = {};
const choice = {hints:{}, categories:{}, oneshots:{}};
D.hints.forEach(h => { choice.hints[h.key] = h.default;
                       if (h.defaultOneshot) choice.oneshots[h.key] = h.defaultOneshot; });
D.categories.forEach(c => choice.categories[c.key] = c.default || "");

document.getElementById("prov").textContent =
  `${D.source} · 셀 ${CW}x${CH} · 동작 ${D.poses.length}종`;
document.getElementById("path").textContent = D.mappingPath;

/* ---- frame selection, mirroring the renderer ---- */
function clipCell(clip, t){
  const total = clip.durations.reduce((a,b)=>a+b,0);
  if (clip.loop) t = ((t % total) + total) % total;
  else if (t >= total) return clip.durations.length - 1;
  let cursor = 0;
  for (let i=0;i<clip.durations.length;i++){ cursor += clip.durations[i]; if (t < cursor) return i; }
  return clip.durations.length - 1;
}
const blinkTotal = D.idle.blink.reduce((a,s)=>a+s[1],0);
function eyeAt(t, seed){
  const [lo,hi] = D.idle.blinkInterval;
  const period = blinkTotal + lo + ((seed*9301+49297)%233280)/233280*(hi-lo);
  const p = ((t % period) + period) % period;
  if (p >= blinkTotal) return "open";
  let cursor = 0;
  for (const [name,ms] of D.idle.blink){ cursor += ms; if (p < cursor) return name; }
  return "open";
}
function layersFor(pose, t, seed){
  if (pose === D.idle.pose){
    return [["idle", D.idle.eyeCells[eyeAt(t, seed)]],
            ["steam", Math.floor(t / D.idle.steamFrameMs) % D.idle.steamCells]];
  }
  const clip = D.clips[pose];
  if (!clip) return [];
  return [[clip.sheet, clipCell(clip, t)]];
}

/* ---- canvases ---- */
const painters = [];
function addCanvas(el, poseGetter, seed){
  el.width = CW; el.height = CH;
  const ctx = el.getContext("2d");
  painters.push(t => {
    const pose = poseGetter();
    ctx.clearRect(0,0,CW,CH);
    if (!pose) return;
    for (const [sheet, cell] of layersFor(pose, t, seed)){
      const img = images[sheet];
      if (img) ctx.drawImage(img, cell*CW, 0, CW, CH, 0, 0, CW, CH);
    }
  });
}

const poseBox = document.getElementById("poses");
D.poses.concat(Object.keys(D.clips).filter(n => !D.poses.includes(n))).forEach((pose, i) => {
  const clip = D.clips[pose];
  const card = document.createElement("div");
  card.className = "pose" + (clip && !clip.loop ? " oneshot" : "");
  const cv = document.createElement("canvas");
  card.appendChild(cv);
  const total = clip ? clip.durations.reduce((a,b)=>a+b,0) : 2400;
  card.insertAdjacentHTML("beforeend",
    `<div class="name">${pose}</div><div class="ms">${total}ms${clip && !clip.loop ? " · 1회" : ""}</div>`);
  poseBox.appendChild(card);
  addCanvas(cv, () => pose, i + 1);
});

function optionsFor(selected){
  return D.poses.map(p => `<option value="${p}"${p===selected?" selected":""}>${p}</option>`).join("");
}
function row(tbody, item, bucket, allowInherit){
  const tr = document.createElement("tr");
  const inherit = allowInherit ? `<option value=""${!item.default?" selected":""}>— generating 따름</option>` : "";
  tr.innerHTML =
    `<td class="key">${item.key}</td><td class="note">${item.note}</td>` +
    `<td><select>${inherit}${optionsFor(choice[bucket][item.key])}</select></td>` +
    `<td class="thumb"><canvas></canvas></td>`;
  tbody.appendChild(tr);
  const sel = tr.querySelector("select");
  sel.value = choice[bucket][item.key] || "";
  sel.addEventListener("change", () => {
    choice[bucket][item.key] = sel.value;
    tr.classList.toggle("changed", sel.value !== (item.default || ""));
    emit();
  });
  addCanvas(tr.querySelector("canvas"),
            () => choice[bucket][item.key] || (bucket === "categories" ? choice.hints.generating : null),
            item.key.length);
  return () => { sel.value = item.default || ""; choice[bucket][item.key] = item.default || "";
                 tr.classList.remove("changed"); };
}
const resetters = [];
D.hints.forEach(h => resetters.push(row(document.getElementById("hints"), h, "hints", false)));
D.categories.forEach(c => resetters.push(row(document.getElementById("cats"), c, "categories", true)));

/* ---- export ---- */
function payload(){
  const doc = {version:1};
  const hints = {}, cats = {}, ones = {};
  D.hints.forEach(h => {
    if (choice.hints[h.key] !== h.default) hints[h.key] = choice.hints[h.key];
    const now = choice.oneshots[h.key] || "";
    if (now !== (h.defaultOneshot || "")) ones[h.key] = now || null;
  });
  D.categories.forEach(c => { if (choice.categories[c.key] !== (c.default || "")) {
    if (choice.categories[c.key]) cats[c.key] = choice.categories[c.key];
  }});
  if (Object.keys(hints).length) doc.hints = hints;
  if (Object.keys(cats).length) doc.categories = cats;
  if (Object.keys(ones).length) doc.oneshots = ones;
  return doc;
}
const out = document.getElementById("out");
const said = document.getElementById("said");
function emit(){
  const doc = payload();
  out.value = (doc.hints || doc.categories || doc.oneshots)
    ? JSON.stringify(doc, null, 2)
    : "// 기본값 그대로다. 바꾼 항목이 없으면 파일을 둘 필요가 없다.";
  said.textContent = "";
}
function flash(message){ said.textContent = message; setTimeout(() => said.textContent = "", 2400); }
document.getElementById("copy").addEventListener("click", async () => {
  try { await navigator.clipboard.writeText(out.value); flash("복사했다"); }
  catch { out.select(); flash("직접 복사해라"); }
});
document.getElementById("download").addEventListener("click", () => {
  const blob = new Blob([out.value], {type:"application/json"});
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob); a.download = D.mappingFile; a.click();
  URL.revokeObjectURL(a.href); flash(D.mappingFile + " 저장");
});
document.getElementById("reset").addEventListener("click", () => { resetters.forEach(r => r()); emit(); });

/* ---- run ---- */
let loaded = 0, total = Object.keys(D.sheets).length;
for (const [name, sheet] of Object.entries(D.sheets)){
  const img = new Image();
  img.onload = img.onerror = () => { if (++loaded === total) requestAnimationFrame(frame); };
  img.src = sheet.src;
  images[name] = img;
}
const started = performance.now();
function frame(now){
  const t = now - started;
  for (const paint of painters) paint(t);
  requestAnimationFrame(frame);
}
emit();
</script>
</body>
</html>
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--open", action="store_true", help="open the page when it is written")
    arguments = parser.parse_args()

    payload = build_payload()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        TEMPLATE.replace("__PAYLOAD__", json.dumps(payload, ensure_ascii=False)), encoding="utf-8"
    )
    size = OUTPUT.stat().st_size / 1024 / 1024
    print(f"{OUTPUT}  ({size:.1f} MiB, {len(payload['poses'])} selectable poses)")
    print(f"chosen mapping goes to {payload['mappingPath']}")
    if arguments.open:
        webbrowser.open(OUTPUT.as_uri())


if __name__ == "__main__":
    main()
