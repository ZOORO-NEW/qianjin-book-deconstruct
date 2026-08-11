#!/usr/bin/env python3
"""Render a 拆书 study guide (Markdown) into a standalone HTML learning manual.

Usage:
    python scripts/render.py input.md -o output.html
    python scripts/render.py input.md            # writes input.html alongside

The script relies ONLY on the standard library. It splits the document on the
fixed `##` section headers produced by the book-deconstruct skill and builds a
clickable table-of-contents sidebar, then converts the body to clean HTML.
"""

import argparse
import html
import os
import re

# --------------------------------------------------------------------------- #
# Inline + block Markdown conversion (minimal, stdlib-only)
# --------------------------------------------------------------------------- #

def inline(text: str) -> str:
    text = html.escape(text)
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"__([^_]+)__", r"<strong>\1</strong>", text)
    return text


def _is_table_sep(line: str) -> bool:
    s = line.strip().strip("|")
    if "|" in s:
        cells = [c.strip() for c in s.split("|")]
    else:
        cells = [s]
    cells = [c for c in cells if c != ""]
    return len(cells) > 0 and all(set(c) <= set("-:") and "-" in c for c in cells)


def render_table(rows):
    body = []
    for idx, row in enumerate(rows):
        cells = [c.strip() for c in row.strip().strip("|").split("|")]
        tag = "th" if idx == 0 else "td"
        body.append("<tr>" + "".join(f"<{tag}>{inline(c)}</{tag}>" for c in cells) + "</tr>")
    return '<table class="grid">' + "".join(body) + "</table>"


def blocks_to_html(lines):
    out = []
    i, n = 0, len(lines)
    while i < n:
        i0 = i
        line = lines[i].rstrip("\n")
        if not line.strip():
            i += 1
            continue
        stripped = line.lstrip()
        # fenced code
        if stripped.startswith("```"):
            i += 1
            code = []
            while i < n and not lines[i].lstrip().startswith("```"):
                code.append(lines[i].rstrip("\n"))
                i += 1
            i += 1
            out.append("<pre><code>" + html.escape("\n".join(code)) + "</code></pre>")
            continue
        # table
        if stripped.startswith("|") and i + 1 < n and _is_table_sep(lines[i + 1]):
            rows = []
            while i < n and lines[i].lstrip().startswith("|"):
                rows.append(lines[i].rstrip("\n"))
                i += 1
            out.append(render_table(rows))
            continue
        # blockquote
        if stripped.startswith(">"):
            quote = []
            while i < n and lines[i].lstrip().startswith(">"):
                quote.append(lines[i].lstrip()[1:].strip())
                i += 1
            out.append("<blockquote>" + " ".join(inline(q) for q in quote) + "</blockquote>")
            continue
        # unordered list
        if re.match(r"^\s*[-*]\s+", line):
            items = []
            while i < n and re.match(r"^\s*[-*]\s+", lines[i]):
                items.append(re.sub(r"^\s*[-*]\s+", "", lines[i].rstrip("\n")))
                i += 1
            out.append("<ul>" + "".join(f"<li>{inline(it)}</li>" for it in items) + "</ul>")
            continue
        # ordered list (only when >=2 consecutive numbered items)
        if re.match(r"^\s*\d+\.\s+", line) and i + 1 < n and re.match(r"^\s*\d+\.\s+", lines[i + 1]):
            items = []
            while i < n and re.match(r"^\s*\d+\.\s+", lines[i]):
                items.append(re.sub(r"^\s*\d+\.\s+", "", lines[i].rstrip("\n")))
                i += 1
            out.append("<ol>" + "".join(f"<li>{inline(it)}</li>" for it in items) + "</ol>")
            continue
        # paragraph (gather until blank / block start; allow indented continuations)
        para = []
        while i < n and lines[i].strip():
            s = lines[i]
            st = s.lstrip()
            if st.startswith("|") or st.startswith(">") or re.match(r"^\s*[-*]\s+", s):
                break
            if re.match(r"^\s*\d+\.\s+", s) and i + 1 < n and re.match(r"^\s*\d+\.\s+", lines[i + 1]):
                break
            para.append(s.rstrip("\n"))
            i += 1
        out.append("<p>" + inline(" ".join(para)) + "</p>")
    if i == i0:  # safety net: never spin forever on an unrecognized line
        i += 1
    return "\n".join(out)


# --------------------------------------------------------------------------- #
# Document parsing
# --------------------------------------------------------------------------- #

def parse_doc(raw: str):
    lines = raw.split("\n")
    title = "拆书学习手册"
    # find first level-1 heading
    for ln in lines:
        if ln.startswith("# ") and not ln.startswith("## "):
            title = ln[2:].strip()
            break
    # split into ## sections
    sections = []
    cur = None
    sec_id = 0
    for ln in lines:
        if ln.startswith("## ") and not ln.startswith("### "):
            sec_id += 1
            cur = {"title": ln[3:].strip(), "id": f"sec-{sec_id}",
                   "subs": [], "body": []}
            sections.append(cur)
        elif ln.startswith("### ") and cur is not None:
            cur["subs"].append({"title": ln[4:].strip(),
                                 "id": f"{cur['id']}-sub-{len(cur['subs']) + 1}",
                                 "body": []})
        elif cur is not None:
            if cur["subs"]:
                cur["subs"][-1]["body"].append(ln)
            else:
                cur["body"].append(ln)
    return title, sections


# --------------------------------------------------------------------------- #
# HTML assembly
# --------------------------------------------------------------------------- #

CSS = """
:root{
  --bg:#f7f5f0; --panel:#ffffff; --ink:#23201b; --muted:#7a746a;
  --line:#e7e2d8; --accent:#9a6a3c; --accent2:#3c6a9a; --soft:#f1ece2;
}
*{box-sizing:border-box}
body{margin:0;font-family:-apple-system,"PingFang SC","Microsoft YaHei",Segoe UI,Roboto,sans-serif;
  background:var(--bg);color:var(--ink);line-height:1.75;}
.layout{display:flex;min-height:100vh;}
.side{width:280px;flex:0 0 280px;background:var(--panel);border-right:1px solid var(--line);
  position:sticky;top:0;height:100vh;overflow:auto;padding:28px 18px;}
.side h2{font-size:13px;letter-spacing:.12em;color:var(--muted);text-transform:uppercase;margin:0 0 12px;}
.side a{display:block;color:var(--ink);text-decoration:none;padding:7px 10px;border-radius:8px;
  font-size:14px;margin-bottom:2px;}
.side a:hover{background:var(--soft);}
.side a.sub{padding-left:26px;font-size:13px;color:var(--muted);}
.content{flex:1;max-width:880px;margin:0 auto;padding:48px 56px 96px;}
.content h1{font-size:30px;margin:0 0 6px;}
.content h2{font-size:22px;margin:42px 0 14px;padding-bottom:8px;border-bottom:2px solid var(--accent);color:var(--accent);}
.content h3{font-size:18px;margin:26px 0 10px;color:var(--accent2);}
.content p{margin:10px 0;}
.content ul,.content ol{margin:10px 0;padding-left:22px;}
.content li{margin:5px 0;}
.content blockquote{margin:14px 0;padding:12px 18px;background:var(--soft);border-left:4px solid var(--accent);
  border-radius:0 8px 8px 0;color:var(--muted);}
.content code{background:var(--soft);padding:1px 6px;border-radius:4px;font-size:.9em;}
.content pre{background:#2b2620;color:#f3ead9;padding:16px 18px;border-radius:10px;overflow:auto;}
.content pre code{background:none;color:inherit;padding:0;}
.content table.grid{border-collapse:collapse;width:100%;margin:14px 0;font-size:14px;background:var(--panel);}
.content table.grid th,.content table.grid td{border:1px solid var(--line);padding:9px 12px;text-align:left;vertical-align:top;}
.content table.grid th{background:var(--soft);color:var(--accent);}
.meta{color:var(--muted);font-size:13px;margin-bottom:24px;}
@media(max-width:760px){.side{display:none}.content{padding:28px 20px}}
"""


def build_html(title, sections):
    toc = ['<nav class="side"><h2>目录</h2>']
    main = [f'<main class="content"><h1>{html.escape(title)}</h1>'
            f'<div class="meta">由 book-deconstruct 技能生成 · 系统化学习手册</div>']
    for s in sections:
        toc.append(f'<a href="#{s["id"]}">{html.escape(s["title"])}</a>')
        main.append(f'<h2 id="{s["id"]}">{html.escape(s["title"])}</h2>')
        main.append(blocks_to_html(s["body"]))
        for sub in s["subs"]:
            toc.append(f'<a class="sub" href="#{sub["id"]}">{html.escape(sub["title"])}</a>')
            main.append(f'<h3 id="{sub["id"]}">{html.escape(sub["title"])}</h3>')
            main.append(blocks_to_html(sub["body"]))
    toc.append("</nav>")
    main.append("</main>")
    return ("<!DOCTYPE html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            f"<title>{html.escape(title)}</title><style>{CSS}</style></head>"
            "<body><div class=\"layout\">" + "".join(toc) + "".join(main) + "</div></body></html>")


def main():
    ap = argparse.ArgumentParser(description="Render a 拆书 study guide to HTML.")
    ap.add_argument("input", help="Markdown study guide (.md)")
    ap.add_argument("-o", "--output", help="Output HTML path (default: <input>.html)")
    args = ap.parse_args()
    with open(args.input, "r", encoding="utf-8") as f:
        raw = f.read()
    title, sections = parse_doc(raw)
    out_html = build_html(title, sections)
    out_path = args.output or os.path.splitext(args.input)[0] + ".html"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(out_html)
    print(f"✅ 已生成学习手册：{out_path}（{len(sections)} 个章节）")


if __name__ == "__main__":
    main()
