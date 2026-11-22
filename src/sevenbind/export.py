"""Bindings sheet: a readable page of every binding in a backup, plus CSV.

The page is a self-contained HTML file in 7Net's look; it prints cleanly
(light theme on paper), so "Print → Save as PDF" gives the PDF.
Only the player's own changes are in a backup; game defaults come later from
7hills.space (defaultProfile.xml per build).
"""

from __future__ import annotations

import csv
import html
import io
from pathlib import Path

from . import actionmaps, gamefiles
from .paths import sub

PRESS_LABEL = {"tap": "", "hold": "HOLD", "double_tap": "2× TAP", "modifier": "+ MOD"}


def _profile(files: dict[str, bytes]) -> actionmaps.Profile | None:
    data = files.get(gamefiles.ACTIONMAPS)
    return actionmaps.parse(data) if data else None


def csv_text(files: dict[str, bytes]) -> str:
    p = _profile(files)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["device", "device_key", "input", "input_label", "press", "action", "action_label", "category", "source", "notes", "conflict"])
    if p:
        clash = {(c["input"].lower(), c["press"]) for c in actionmaps.conflicts(p)}
        for r in actionmaps.rows(p):
            w.writerow([r["device"], r["device_key"], r["input"], r["input_label"], r["press"], r["action"],
                        r["action_label"], r["category"], r["source"], ";".join(r["notes"]),
                        "yes" if (r["input"].lower(), r["press"]) in clash and r["source"] == "mine" else ""])
    return buf.getvalue()


def _sort_key(r: dict) -> tuple:
    import re
    m = re.search(r"(\d+)", r["input_label"])
    axis = 0 if "axis" in r["input_label"] or "Slider" in r["input_label"] else 1
    return (r["source"] == "removed", axis, int(m.group(1)) if m else 0, r["input_label"], r["action_label"])


def html_sheet(files: dict[str, bytes], meta: dict, owner: str | None = None) -> str:
    p = _profile(files)
    e = html.escape
    title = f"{owner or 'My'} · bindings"
    sub_line = " · ".join(x for x in [meta.get("channel"), f"game {meta['game_version']}" if meta.get("game_version") else None,
                                      f"build {meta['game_build']}" if meta.get("game_build") else None,
                                      f"backup {(meta.get('created_at') or '').replace('T', ' ')[:16]}"] if x)
    cards = []
    if p:
        clash = {(c["input"].lower(), c["press"]) for c in actionmaps.conflicts(p)}
        rows = actionmaps.rows(p)
        order = []
        for d in p.devices:
            if d.kind == "keyboard":
                order.append(("kb", d.instance, "Keyboard", f"kb{d.instance}"))
        order.append(("mo", 1, "Mouse", "mo1"))
        for d in sorted(p.joysticks, key=lambda d: d.instance):
            order.append(("js", d.instance, d.name, f"js{d.instance}"))
        seen = set()
        for _, _, name, key in order:
            if key in seen:
                continue
            seen.add(key)
            rs = sorted([r for r in rows if r["device_key"] == key], key=_sort_key)
            if not rs:
                continue
            mine = sum(1 for r in rs if r["source"] == "mine")
            gone = len(rs) - mine
            lines = []
            for r in rs:
                cls = "removed" if r["source"] == "removed" else ""
                if r["source"] == "mine" and (r["input"].lower(), r["press"]) in clash:
                    cls = "clash"
                pill = PRESS_LABEL.get(r["press"], "")
                note = (" <span class='note'>" + e(" · ".join(r["notes"])) + "</span>") if r["notes"] else ""
                if r["source"] == "removed":
                    note += " <span class='note'>removed by you</span>"
                lines.append(
                    f"<tr class='{cls}'><td><span class='key'>{e(r['input_label'])}</span></td>"
                    f"<td>{'<span class=pill>' + e(pill) + '</span>' if pill else ''}</td>"
                    f"<td class='act'>{e(r['action_label'])}{note}</td><td class='cat'>{e(r['category'])}</td></tr>")
            meta_line = f"{key} · {mine} binding{'s' if mine != 1 else ''}" + (f" · {gone} removed" if gone else "")
            cards.append(f"<section><header><h2>{e(name)}</h2><span>{e(meta_line)}</span></header>"
                         f"<table>{''.join(lines)}</table></section>")
        clash_list = actionmaps.conflicts(p)
        warn = ""
        if clash_list:
            items = "".join(f"<li><b>{e(c['input'])}</b>: {e(' + '.join(c['labels']))}</li>" for c in clash_list)
            warn = f"<div class='warn'><b>{len(clash_list)} input{'s do' if len(clash_list) != 1 else ' does'} two things</b><ul>{items}</ul></div>"
    else:
        warn = "<p>This backup has no bindings file.</p>"
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>{e(title)}</title>
<style>
:root{{--gold:#f0b443}}*{{box-sizing:border-box}}
body{{margin:0;background:#0a0a0a;color:#e8e8e8;font:14px/1.45 Inter,'Segoe UI',sans-serif;padding:32px}}
h1{{font:800 40px 'Barlow Condensed','Segoe UI',sans-serif;text-transform:uppercase;margin:4px 0 0;letter-spacing:.02em}}
.eyebrow{{color:var(--gold);font-size:12px;letter-spacing:.14em;text-transform:uppercase;font-weight:600}}
.sub{{color:#9a9a9a;margin:6px 0 22px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(420px,1fr));gap:16px;align-items:start}}
section{{background:#111;border:1px solid #1f1f1f;border-radius:10px;overflow:hidden;break-inside:avoid}}
section header{{display:flex;justify-content:space-between;align-items:baseline;gap:10px;padding:12px 16px;background:#0d0d0d;border-bottom:1px solid #1f1f1f}}
section h2{{margin:0;font:800 21px 'Barlow Condensed','Segoe UI',sans-serif;text-transform:uppercase}}
section header span{{color:#9a9a9a;font-size:12px}}
table{{width:100%;border-collapse:collapse}}td{{padding:7px 10px;border-top:1px solid #1a1a1a;vertical-align:middle}}
td:first-child{{width:120px;padding-left:16px}}td:nth-child(2){{width:70px}}
.key{{display:inline-block;font:12px 'JetBrains Mono',Consolas,monospace;background:#1a1a1a;border:1px solid #2a2a2a;border-bottom-width:3px;border-radius:4px;padding:2px 8px}}
.pill{{font-size:10px;font-weight:600;letter-spacing:.08em;color:var(--gold);border:1px solid #5c4519;border-radius:10px;padding:2px 7px}}
.cat{{color:#9a9a9a;font-size:11px;text-transform:uppercase;letter-spacing:.06em;text-align:right;padding-right:16px}}
.note{{color:var(--gold);font-size:12px}}
tr.removed .act{{color:#9a9a9a;text-decoration:line-through}}tr.removed .note{{text-decoration:none;display:inline-block}}
tr.clash{{background:#1f1212}}tr.clash .key{{color:#fca5a5;border-color:#7f1d1d}}
.warn{{border:1px solid #5c4519;background:#1a1508;border-radius:8px;padding:12px 16px;margin:0 0 18px}}.warn ul{{margin:6px 0 0;padding-left:18px}}
footer{{color:#9a9a9a;font-size:12px;margin-top:20px}}
@media print{{body{{background:#fff;color:#111;padding:0}}section{{background:#fff;border-color:#ccc}}section header{{background:#f3f3f3;border-color:#ccc}}
td{{border-color:#e3e3e3}}.key{{background:#f5f5f5;border-color:#bbb;color:#111}}tr.clash{{background:#fde8e8}}.warn{{background:#fff7e6}}
.sub,.cat,section header span,footer{{color:#555}}.eyebrow,.note,.pill{{color:#8a5a00}}}}
</style></head><body>
<div class="eyebrow">Bindings sheet · 7Bind</div><h1>{e(title)}</h1><div class="sub">{e(sub_line)}</div>
{warn}<div class="grid">{''.join(cards)}</div>
<footer>Shows the bindings you changed and the defaults you removed. Game defaults you kept are not in the backup. Print → Save as PDF for a PDF.</footer>
</body></html>"""


def write_exports(files: dict[str, bytes], meta: dict, owner: str | None = None) -> dict:
    out = sub("exports")
    stem = f"bindings-{meta.get('channel', 'X')}-{(meta.get('created_at') or 'now')[:16].replace(':', '').replace('T', '-')}"
    h = out / f"{stem}.html"
    c = out / f"{stem}.csv"
    h.write_text(html_sheet(files, meta, owner), encoding="utf-8")
    c.write_text(csv_text(files), encoding="utf-8-sig", newline="")
    return {"html": str(h), "csv": str(c)}


def open_path(path: str | Path) -> None:
    import os
    import sys
    import webbrowser
    if sys.platform == "win32":
        os.startfile(str(path))   # type: ignore[attr-defined]
    else:
        webbrowser.open(Path(path).as_uri())
