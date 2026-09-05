"""Generate one page for choosing what every sprite overlay draws.

Each sprite overlay describes itself with a :class:`SpriteMap`, so this script
knows nothing about any particular one: it walks the registry, collects whatever
exposes ``sprite_map()``, and emits a tab per overlay. Adding a sprite overlay
adds a tab; nothing here changes.

The page plays the packed cells the renderer actually draws, at the declared
timings, and exports only what differs from the defaults.

Usage:
    python scripts/build-sprite-preview.py
    python scripts/build-sprite-preview.py --open
"""

from __future__ import annotations

import argparse
import base64
import importlib
import json
import sys
import webbrowser
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from engram_overlay.overlays.spritemap import MAPPING_FILE, SpriteMap  # noqa: E402
from engram_overlay.registry import overlay_catalog  # noqa: E402

OUTPUT = REPO_ROOT / "dist" / "sprite-mapping.html"


def discover() -> list[SpriteMap]:
    """Every registered overlay that offers a mapping, in registry order."""
    maps: list[SpriteMap] = []
    for spec in overlay_catalog():
        module = importlib.import_module(spec.module)
        factory = getattr(module, "sprite_map", None)
        if callable(factory):
            maps.append(factory())
    return maps


def data_uri(path: Path) -> str:
    return "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode("ascii")


def describe(sprite_map: SpriteMap) -> dict[str, object]:
    return {
        "id": sprite_map.overlay_id,
        "name": sprite_map.name,
        "cell": list(sprite_map.cell),
        "mappingPath": str(sprite_map.mapping_path),
        "sheets": {
            name: {
                "src": data_uri(sprite_map.asset_dir / file_name),
                "count": count,
                "columns": columns,
            }
            for name, (file_name, count, columns) in sprite_map.sheets.items()
        },
        "options": {
            key: {
                "note": option.note,
                "totalMs": option.total_ms,
                "loops": option.loops,
                "layers": [
                    {
                        "sheet": layer.sheet,
                        "cells": list(layer.cells),
                        "durations": list(layer.durations_ms),
                        "loop": layer.loop,
                    }
                    for layer in option.layers
                ],
            }
            for key, option in sprite_map.options.items()
        },
        "sections": [
            {
                "key": section.key,
                "title": section.title,
                "note": section.note,
                "multi": section.multi,
                "allowEmpty": section.allow_empty,
                "options": list(section.options),
                "rows": [
                    {"key": row.key, "note": row.note, "default": list(row.default)}
                    for row in section.rows
                ],
            }
            for section in sprite_map.sections
        ],
    }


TEMPLATE = """<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>스프라이트 매핑</title>
<style>
  :root{
    --ground:#f4f6f8;--surface:#fff;--sunken:#e9edf1;--ink:#161b21;--ink-soft:#414d5a;
    --muted:#6d7a88;--rule:#d5dce3;--accent:#1f5f8b;--accent-soft:#e2eef6;--ok:#2f6b4f;
    --sans:"Segoe UI",system-ui,-apple-system,sans-serif;
    --mono:"Cascadia Mono",Consolas,ui-monospace,monospace;
  }
  @media (prefers-color-scheme:dark){:root{
    --ground:#0f1419;--surface:#171d24;--sunken:#1e262f;--ink:#e6ebf0;--ink-soft:#b3bec9;
    --muted:#8794a2;--rule:#2b333d;--accent:#78b0d6;--accent-soft:#16303f;--ok:#7cc7a0;
  }}
  *{box-sizing:border-box}
  body{margin:0;background:var(--ground);color:var(--ink);font-family:var(--sans);line-height:1.65}
  .page{max-width:1180px;margin:0 auto;padding:2.25rem 1.25rem 5rem}
  h1{font-size:1.6rem;margin:0 0 .3rem;letter-spacing:-.01em}
  .sub{color:var(--ink-soft);margin:0 0 1.5rem;max-width:70ch}
  h2{font-size:.78rem;font-family:var(--mono);letter-spacing:.14em;text-transform:uppercase;
     color:var(--muted);font-weight:600;display:flex;align-items:center;gap:1rem;margin:2.5rem 0 .5rem}
  h2::after{content:"";flex:1;height:1px;background:var(--rule)}
  .note{color:var(--muted);font-size:.86rem;margin:.25rem 0 1.1rem;max-width:78ch}

  .tabs{display:flex;gap:.35rem;border-bottom:2px solid var(--rule);margin:0 0 1.75rem}
  .tabs button{font-family:var(--sans);font-size:.92rem;padding:.5rem .95rem;border:0;
    background:none;color:var(--muted);cursor:pointer;border-bottom:2px solid transparent;margin-bottom:-2px}
  .tabs button[aria-selected="true"]{color:var(--ink);border-bottom-color:var(--accent);font-weight:600}
  .tabs button:focus-visible{outline:2px solid var(--accent);outline-offset:-2px}
  .tabs .count{font-family:var(--mono);font-size:.72rem;color:var(--muted);margin-left:.35rem}

  .poses{display:grid;grid-template-columns:repeat(auto-fill,minmax(126px,1fr));gap:.85rem}
  .pose{background:var(--surface);border:1px solid var(--rule);border-radius:4px;padding:.5rem;text-align:center}
  .pose canvas{width:100%;height:auto;display:block}
  .pose .name{font-family:var(--mono);font-size:.75rem;margin-top:.35rem}
  .pose .ms{font-family:var(--mono);font-size:.65rem;color:var(--muted)}
  .pose.once{border-style:dashed}

  table{width:100%;border-collapse:collapse;font-size:.9rem}
  th,td{text-align:left;padding:.45rem .6rem;border-bottom:1px solid var(--rule);vertical-align:middle}
  thead th{font-family:var(--mono);font-size:.67rem;letter-spacing:.1em;text-transform:uppercase;
           color:var(--muted);font-weight:600}
  td.key{font-family:var(--mono);white-space:nowrap}
  td.note{color:var(--muted);font-size:.83rem}
  td.thumb{width:60px}
  td.thumb canvas{width:52px;height:auto;display:block;background:var(--sunken);border-radius:3px}
  select{font-family:var(--mono);font-size:.84rem;padding:.25rem .35rem;background:var(--surface);
         color:var(--ink);border:1px solid var(--rule);border-radius:3px;min-width:9rem}
  select:focus-visible{outline:2px solid var(--accent);outline-offset:1px}
  .chips{display:flex;flex-wrap:wrap;gap:.3rem}
  .chips label{font-family:var(--mono);font-size:.78rem;padding:.15rem .45rem;border-radius:3px;
    border:1px solid var(--rule);background:var(--surface);cursor:pointer;user-select:none}
  .chips input{position:absolute;opacity:0;pointer-events:none}
  .chips input:checked+span{color:var(--accent);font-weight:600}
  .chips label:has(input:checked){border-color:var(--accent);background:var(--accent-soft)}
  .chips label:has(input:focus-visible){outline:2px solid var(--accent);outline-offset:1px}
  tr.changed td.key{color:var(--accent);font-weight:600}
  tr.changed td.key::after{content:" ●"}

  .bar{display:flex;flex-wrap:wrap;gap:.55rem;align-items:center;margin:1.1rem 0 .8rem}
  button.act{font-family:var(--sans);font-size:.87rem;padding:.42rem .85rem;border-radius:3px;
    border:1px solid var(--rule);background:var(--surface);color:var(--ink);cursor:pointer}
  button.act.primary{background:var(--accent);border-color:var(--accent);color:#fff}
  button.act:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
  .said{color:var(--ok);font-size:.84rem;font-family:var(--mono)}
  textarea{width:100%;min-height:10rem;font-family:var(--mono);font-size:.79rem;line-height:1.55;
    background:var(--sunken);color:var(--ink-soft);border:1px solid var(--rule);border-radius:4px;padding:.75rem}
  code{font-family:var(--mono);background:var(--sunken);padding:.1em .35em;border-radius:2px;font-size:.88em}
  .path{font-family:var(--mono);font-size:.79rem;color:var(--ink-soft);word-break:break-all;
        background:var(--accent-soft);padding:.55rem .7rem;border-radius:3px;margin:.35rem 0 0}
  [hidden]{display:none!important}
</style>
</head>
<body>
<div class="page">
  <h1>스프라이트 매핑</h1>
  <p class="sub">각 신호에 어떤 그림을 붙일지 고른다. 미리보기는 오버레이가 실제로 그리는 셀을 같은 타이밍으로 재생한다.</p>
  <div class="tabs" id="tabs" role="tablist"></div>
  <div id="panels"></div>
</div>

<script id="payload" type="application/json">__PAYLOAD__</script>
<script>
const DATA = JSON.parse(document.getElementById("payload").textContent);
const painters = [];
const state = {};   // overlay id -> {section -> {row -> [values]}}

function cellRect(sheet, index){
  const col = index % sheet.columns, row = Math.floor(index / sheet.columns);
  return [col, row];
}
function pickCell(layer, t){
  const total = layer.durations.reduce((a,b)=>a+b,0);
  let time = t;
  if (layer.loop) time = ((time % total) + total) % total;
  else if (time >= total) return layer.cells[layer.cells.length-1];
  let cursor = 0;
  for (let i=0;i<layer.durations.length;i++){ cursor += layer.durations[i]; if (time < cursor) return layer.cells[i]; }
  return layer.cells[layer.cells.length-1];
}

function makeCanvas(ov, el, valuesGetter){
  const [CW, CH] = ov.cell;
  el.width = CW; el.height = CH;
  const ctx = el.getContext("2d");
  painters.push(t => {
    ctx.clearRect(0,0,CW,CH);
    const values = valuesGetter();
    if (!values || !values.length) return;
    // Several candidates rotate on a slow cycle so a multi-select shows them all.
    const key = values.length === 1 ? values[0] : values[Math.floor(t/1200) % values.length];
    const option = ov.options[key];
    if (!option) return;
    for (const layer of option.layers){
      const img = ov._img[layer.sheet];
      const sheet = ov.sheets[layer.sheet];
      if (!img || !sheet) continue;
      const [col, row] = cellRect(sheet, pickCell(layer, t));
      ctx.drawImage(img, col*CW, row*CH, CW, CH, 0, 0, CW, CH);
    }
  });
}

function buildPanel(ov){
  const panel = document.createElement("section");
  panel.id = "panel-" + ov.id;
  panel.setAttribute("role", "tabpanel");

  const poses = document.createElement("div");
  poses.className = "poses";
  for (const [key, option] of Object.entries(ov.options)){
    const card = document.createElement("div");
    card.className = "pose" + (option.loops ? "" : " once");
    const cv = document.createElement("canvas");
    card.appendChild(cv);
    card.insertAdjacentHTML("beforeend",
      `<div class="name">${key}</div><div class="ms">${option.totalMs}ms${option.loops?"":" · 1회"}</div>`);
    poses.appendChild(card);
    makeCanvas(ov, cv, () => [key]);
  }
  panel.insertAdjacentHTML("beforeend", "<h2>동작</h2>");
  panel.appendChild(poses);

  const resetters = [];
  for (const section of ov.sections){
    state[ov.id][section.key] = {};
    panel.insertAdjacentHTML("beforeend",
      `<h2>${section.title}</h2>` + (section.note ? `<p class="note">${section.note}</p>` : ""));
    const table = document.createElement("table");
    table.innerHTML = `<thead><tr><th>신호</th><th>의미</th><th>${section.multi?"동작 (여러 개)":"동작"}</th><th></th></tr></thead>`;
    const tbody = document.createElement("tbody");
    table.appendChild(tbody);
    panel.appendChild(table);

    for (const row of section.rows){
      state[ov.id][section.key][row.key] = row.default.slice();
      const tr = document.createElement("tr");
      let control;
      if (section.multi){
        control = section.options.map(o =>
          `<label><input type="checkbox" value="${o}"${row.default.includes(o)?" checked":""}><span>${o}</span></label>`).join("");
        control = `<div class="chips">${control}</div>`;
      } else {
        const empty = section.allowEmpty ? `<option value=""${row.default.length?"":" selected"}>— 없음</option>` : "";
        control = `<select>${empty}` + section.options.map(o =>
          `<option value="${o}"${row.default[0]===o?" selected":""}>${o}</option>`).join("") + "</select>";
      }
      tr.innerHTML = `<td class="key">${row.key}</td><td class="note">${row.note}</td>` +
                     `<td>${control}</td><td class="thumb"><canvas></canvas></td>`;
      tbody.appendChild(tr);

      const cur = () => state[ov.id][section.key][row.key];
      const same = () => JSON.stringify(cur()) === JSON.stringify(row.default);
      const mark = () => tr.classList.toggle("changed", !same());
      if (section.multi){
        const boxes = [...tr.querySelectorAll("input")];
        boxes.forEach(box => box.addEventListener("change", () => {
          state[ov.id][section.key][row.key] = boxes.filter(b=>b.checked).map(b=>b.value);
          mark(); emit(ov);
        }));
        resetters.push(() => { boxes.forEach(b => b.checked = row.default.includes(b.value));
                               state[ov.id][section.key][row.key] = row.default.slice();
                               tr.classList.remove("changed"); });
      } else {
        const sel = tr.querySelector("select");
        sel.addEventListener("change", () => {
          state[ov.id][section.key][row.key] = sel.value ? [sel.value] : [];
          mark(); emit(ov);
        });
        resetters.push(() => { sel.value = row.default[0] || "";
                               state[ov.id][section.key][row.key] = row.default.slice();
                               tr.classList.remove("changed"); });
      }
      makeCanvas(ov, tr.querySelector("canvas"), cur);
    }
  }

  panel.insertAdjacentHTML("beforeend", `<h2>적용</h2>
    <div class="bar">
      <button class="act primary" data-do="copy">JSON 복사</button>
      <button class="act" data-do="save">파일로 저장</button>
      <button class="act" data-do="reset">기본값으로</button>
      <span class="said"></span>
    </div>
    <textarea readonly spellcheck="false"></textarea>
    <p class="note">브라우저 다운로드 폴더에 저장되니 아래 경로로 옮기고 오버레이를 재시작한다.</p>
    <p class="path">${ov.mappingPath}</p>`);

  const out = panel.querySelector("textarea");
  const said = panel.querySelector(".said");
  const flash = m => { said.textContent = m; setTimeout(()=>said.textContent="", 2400); };
  panel.querySelector('[data-do="copy"]').addEventListener("click", async () => {
    try { await navigator.clipboard.writeText(out.value); flash("복사했다"); }
    catch { out.select(); flash("직접 복사해라"); }
  });
  panel.querySelector('[data-do="save"]').addEventListener("click", () => {
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([out.value], {type:"application/json"}));
    a.download = "__MAPPING_FILE__"; a.click(); URL.revokeObjectURL(a.href);
    flash("저장했다 · 다운로드 폴더 확인");
  });
  panel.querySelector('[data-do="reset"]').addEventListener("click", () => { resetters.forEach(r=>r()); emit(ov); });
  ov._out = out;
  return panel;
}

function emit(ov){
  const doc = {version: 1};
  for (const section of ov.sections){
    const changed = {};
    for (const row of section.rows){
      const now = state[ov.id][section.key][row.key];
      if (JSON.stringify(now) === JSON.stringify(row.default)) continue;
      changed[row.key] = section.multi ? now : (now[0] || null);
    }
    if (Object.keys(changed).length) doc[section.key] = changed;
  }
  const empty = Object.keys(doc).length === 1;
  ov._out.value = empty
    ? "// 기본값 그대로다. 바꾼 항목이 없으면 파일을 둘 필요가 없다."
    : JSON.stringify(doc, null, 2);
}

const tabs = document.getElementById("tabs");
const panels = document.getElementById("panels");
DATA.overlays.forEach((ov, index) => {
  state[ov.id] = {};
  ov._img = {};
  const panel = buildPanel(ov);
  panels.appendChild(panel);
  const tab = document.createElement("button");
  tab.type = "button";
  tab.setAttribute("role", "tab");
  tab.innerHTML = `${ov.name}<span class="count">${ov.id}</span>`;
  tab.addEventListener("click", () => select(index));
  tabs.appendChild(tab);
  emit(ov);
});
function select(index){
  DATA.overlays.forEach((ov, i) => {
    panels.children[i].hidden = i !== index;
    tabs.children[i].setAttribute("aria-selected", String(i === index));
  });
}
select(0);

let pending = 0;
DATA.overlays.forEach(ov => {
  for (const [name, sheet] of Object.entries(ov.sheets)){
    pending++;
    const img = new Image();
    img.onload = img.onerror = () => { if (--pending === 0) requestAnimationFrame(frame); };
    img.src = sheet.src;
    ov._img[name] = img;
  }
});
const started = performance.now();
function frame(now){
  const t = now - started;
  for (const paint of painters) paint(t);
  requestAnimationFrame(frame);
}
</script>
</body>
</html>
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--open", action="store_true", help="open the page when it is written")
    arguments = parser.parse_args()

    maps = discover()
    if not maps:
        raise SystemExit("no registered overlay exposes sprite_map()")
    payload = {"overlays": [describe(sprite_map) for sprite_map in maps]}
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        TEMPLATE.replace("__PAYLOAD__", json.dumps(payload, ensure_ascii=False)).replace(
            "__MAPPING_FILE__", MAPPING_FILE
        ),
        encoding="utf-8",
    )
    print(f"{OUTPUT}  ({OUTPUT.stat().st_size / 1024 / 1024:.1f} MiB)")
    for sprite_map in maps:
        rows = sum(len(section.rows) for section in sprite_map.sections)
        print(f"  {sprite_map.overlay_id:14s} {len(sprite_map.options):2d} options, {rows:2d} signals")
    if arguments.open:
        webbrowser.open(OUTPUT.as_uri())


if __name__ == "__main__":
    main()
