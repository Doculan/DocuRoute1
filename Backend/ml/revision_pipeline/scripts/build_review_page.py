"""Build the Checkpoint 4 review page from a built dataset.

The point of the checkpoint is to read generated examples the way the admin
who will rule on them would. That means the *edit*, not the whole section: a
revision submits all twenty rows and changes one, so the page shows a unified
diff of the lines that moved, with the rest accounted for in a line count.

    py ml/revision_pipeline/scripts/build_review_page.py --out review.html
"""

from __future__ import annotations

import argparse
import collections
import difflib
import html
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from revision_pipeline import config, generators                    # noqa: E402
from revision_pipeline.data import load_jsonl                       # noqa: E402

VERDICT_ORDER = {"approve": 0, "needs_revision": 1, "reject": 2}


# ---------------------------------------------------------------- diffing

def _word_marks(old: str, new: str) -> tuple:
    """Mark the words that differ inside a pair of matched lines."""
    old_words = old.split(" ")
    new_words = new.split(" ")
    matcher = difflib.SequenceMatcher(a=old_words, b=new_words)
    old_out, new_out = [], []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        old_part = html.escape(" ".join(old_words[i1:i2]))
        new_part = html.escape(" ".join(new_words[j1:j2]))
        if tag == "equal":
            old_out.append(old_part)
            new_out.append(new_part)
        else:
            if old_part:
                old_out.append(f"<mark class='cut'>{old_part}</mark>")
            if new_part:
                new_out.append(f"<mark class='add'>{new_part}</mark>")
    return " ".join(p for p in old_out if p), " ".join(p for p in new_out if p)


def diff_html(old_text: str, new_text: str) -> tuple:
    """Unified diff of the changed lines. Returns (html, unchanged_line_count)."""
    old_lines = old_text.splitlines()
    new_lines = new_text.splitlines()
    matcher = difflib.SequenceMatcher(a=old_lines, b=new_lines)

    rows, unchanged = [], 0
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            unchanged += i2 - i1
            continue
        removed = old_lines[i1:i2]
        added = new_lines[j1:j2]
        if tag == "replace" and len(removed) == len(added):
            for old_line, new_line in zip(removed, added):
                marked_old, marked_new = _word_marks(old_line, new_line)
                rows.append(f"<div class='line cut'><span class='sign'>-</span>{marked_old}</div>")
                rows.append(f"<div class='line add'><span class='sign'>+</span>{marked_new}</div>")
            continue
        for line in removed:
            rows.append(f"<div class='line cut'><span class='sign'>-</span>{html.escape(line)}</div>")
        for line in added:
            rows.append(f"<div class='line add'><span class='sign'>+</span>{html.escape(line)}</div>")

    return "\n".join(rows), unchanged


# ---------------------------------------------------------------- rendering

def card(example: dict, *, show_score: bool = False) -> str:
    body, unchanged = diff_html(example["old_text"], example["new_text"])
    issues = "".join(
        f"<span class='chip issue'>{html.escape(label)}</span>"
        for label in example["issues"]
    ) or "<span class='chip none'>no issues</span>"

    reason = example.get("change_reason") or ""
    reason_html = (f"<p class='reason'>&ldquo;{html.escape(reason)}&rdquo;</p>"
                   if reason else "<p class='reason none'>no reason given</p>")

    flags = []
    if example.get("strategy"):
        flags.append(
            f"<span class='chip strategy'>{html.escape(example['strategy'])}</span>"
        )
    if example.get("hard_negative"):
        flags.append("<span class='chip hard'>hard negative</span>")
    if show_score:
        flags.append(
            f"<span class='chip score'>score {example.get('quality_score', 1.0):.2f}</span>"
        )
    notes = "".join(
        f"<li>{html.escape(note)}</li>" for note in example.get("quality_notes", [])
    )
    notes_html = f"<ul class='notes'>{notes}</ul>" if notes and show_score else ""
    if example.get("note") and not show_score:
        notes_html = f"<p class='gennote'>{html.escape(example['note'])}</p>"

    unchanged_html = (
        f"<span class='unchanged'>{unchanged} line{'s' if unchanged != 1 else ''} "
        f"unchanged in the submitted section</span>" if unchanged else ""
    )

    return f"""<article class="card">
  <header class="card-head">
    <span class="verdict {example['verdict']}">{example['verdict'].replace('_', ' ')}</span>
    <span class="ident">{html.escape(example['document_no'])}</span>
    <span class="ident">{html.escape(example['section_number'])}</span>
    <span class="sect">{html.escape(example['section_title'][:46])}</span>
    <span class="type">{html.escape(example['section_type'])}</span>
  </header>
  <div class="chips">{issues}{''.join(flags)}</div>
  {reason_html}
  <div class="diff">{body}</div>
  <footer class="card-foot">
    <span>{example['edited_units']} unit{'s' if example['edited_units'] != 1 else ''} edited</span>
    {unchanged_html}
  </footer>
  {notes_html}
</article>"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dataset", default=str(config.DATASET_DIR / "all.jsonl"))
    ap.add_argument("--out", required=True)
    ap.add_argument("--per-generator", type=int, default=5)
    ap.add_argument("--seed", type=int, default=config.SEED + 1)
    args = ap.parse_args()

    rows = load_jsonl(args.dataset)
    rng = random.Random(args.seed)

    by_generator = collections.defaultdict(list)
    for row in rows:
        by_generator[row["generator"]].append(row)

    verdicts = collections.Counter(r["verdict"] for r in rows)
    types = collections.Counter(r["section_type"] for r in rows)
    labels = collections.Counter(l for r in rows for l in r["issues"])
    documents = len({r["document_no"] for r in rows})

    borderline = sorted(rows, key=lambda r: r.get("quality_score", 1.0))[:10]

    # -- sections -------------------------------------------------
    order = sorted(
        by_generator,
        key=lambda name: (VERDICT_ORDER.get(by_generator[name][0]["verdict"], 9), -len(by_generator[name])),
    )

    nav = "".join(
        f"<a href='#g-{name}'><span class='dot {by_generator[name][0]['verdict']}'></span>"
        f"{name.replace('_', ' ')}<em>{len(by_generator[name])}</em></a>"
        for name in order
    )

    sections = []
    for name in order:
        picked = rng.sample(by_generator[name], min(args.per_generator, len(by_generator[name])))
        picked.sort(key=lambda r: r["document_no"])
        cards = "\n".join(card(example) for example in picked)
        verdict = by_generator[name][0]["verdict"]
        sections.append(f"""<section class="gen" id="g-{name}">
  <h3><span class="dot {verdict}"></span>{name.replace('_', ' ')}
      <em>{len(by_generator[name])} in the dataset</em></h3>
  <div class="cards">{cards}</div>
</section>""")

    borderline_cards = "\n".join(card(example, show_score=True) for example in borderline)

    approvals = [r for r in rows if r["verdict"] == "approve"]
    approve_sample = rng.sample(approvals, min(10, len(approvals)))
    approve_sample.sort(key=lambda r: r["generator"])
    approve_cards = "\n".join(card(example) for example in approve_sample)

    label_rows = "".join(
        f"<tr><td>{html.escape(label)}</td><td class='num'>{labels.get(label, 0)}</td>"
        f"<td class='bar'><span style='width:{min(100, labels.get(label, 0) / 4):.0f}%' "
        f"class='{'short' if labels.get(label, 0) < 150 else ''}'></span></td></tr>"
        for label in config.ISSUE_LABELS
    )

    type_rows = "".join(
        f"<tr><td>{html.escape(kind)}</td><td class='num'>{count}</td>"
        f"<td class='num'>{100 * count / len(rows):.0f}%</td></tr>"
        for kind, count in types.most_common()
    )

    out = Path(args.out)
    out.write_text(PAGE.format(
        total=len(rows),
        approve=verdicts["approve"], needs=verdicts["needs_revision"],
        reject=verdicts["reject"], documents=documents,
        generators=len(by_generator), per_generator=args.per_generator,
        nav=nav, sections="\n".join(sections), borderline=borderline_cards,
        approve_cards=approve_cards, approve_total=len(approvals),
        label_rows=label_rows, type_rows=type_rows,
        borderline_total=sum(1 for r in rows if r.get("quality_score", 1.0) < 1.0),
    ), encoding="utf-8")
    print(f"wrote {out}  ({out.stat().st_size / 1024:.0f} KB)")
    return 0


PAGE = """<title>Context v2 Sample Review</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Instrument+Sans:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500;600&display=swap">
<style>
:root {{
  --paper:#f4f2ec; --surface:#fffefb; --sunk:#edeae1;
  --rule:#dedbd0; --rule-soft:#e8e5da;
  --ink:#1f1c17; --muted:#615c50; --subtle:#8a8375;
  --brand:#090749; --brand-600:#4b3fbf; --brand-wash:#eceafa;
  --gold:#b8862c; --gold-ink:#7d5a14; --gold-wash:#faf1dd;
  --ok:#1c7a5a; --ok-soft:#e3f2eb; --ok-ink:#145741;
  --warn:#b8862c; --warn-soft:#faf1dd; --warn-ink:#7d5a14;
  --bad:#a83232; --bad-soft:#fbe9e7; --bad-ink:#7d2620;
  --font-body:"Instrument Sans",system-ui,-apple-system,"Segoe UI",sans-serif;
  --font-mono:"IBM Plex Mono",ui-monospace,"SF Mono",Menlo,monospace;
}}
@media (prefers-color-scheme: dark) {{
  :root:not([data-theme="light"]) {{
    --paper:#15141a; --surface:#1d1c24; --sunk:#232230;
    --rule:#33313f; --rule-soft:#2a2936;
    --ink:#ece9e1; --muted:#a49d90; --subtle:#807a6e;
    --brand:#cdc9ef; --brand-600:#a9a2e2; --brand-wash:#221f3d;
    --gold:#d9a648; --gold-ink:#e8c27c; --gold-wash:#332812;
    --ok:#4cb18c; --ok-soft:#14281f; --ok-ink:#7fd0b0;
    --warn:#d9a648; --warn-soft:#332812; --warn-ink:#e8c27c;
    --bad:#d97070; --bad-soft:#2e1817; --bad-ink:#f0a0a0;
  }}
}}
:root[data-theme="dark"] {{
  --paper:#15141a; --surface:#1d1c24; --sunk:#232230;
  --rule:#33313f; --rule-soft:#2a2936;
  --ink:#ece9e1; --muted:#a49d90; --subtle:#807a6e;
  --brand:#cdc9ef; --brand-600:#a9a2e2; --brand-wash:#221f3d;
  --gold:#d9a648; --gold-ink:#e8c27c; --gold-wash:#332812;
  --ok:#4cb18c; --ok-soft:#14281f; --ok-ink:#7fd0b0;
  --warn:#d9a648; --warn-soft:#332812; --warn-ink:#e8c27c;
  --bad:#d97070; --bad-soft:#2e1817; --bad-ink:#f0a0a0;
}}

* {{ box-sizing:border-box; }}
body {{
  margin:0; background:var(--paper); color:var(--ink);
  font-family:var(--font-body); font-size:15px; line-height:1.55;
  -webkit-font-smoothing:antialiased;
}}
.wrap {{ max-width:1180px; margin:0 auto; padding-inline:20px; padding-block:0 72px; }}

/* ---- masthead ---- */
header.top {{ padding-block:44px 24px; border-bottom:2px solid var(--brand); }}
.eyebrow {{
  font-family:var(--font-mono); font-size:11px; font-weight:600;
  letter-spacing:.14em; text-transform:uppercase; color:var(--gold-ink);
  margin:0 0 10px;
}}
h1 {{ font-size:clamp(28px,4vw,42px); line-height:1.1; margin:0 0 10px; letter-spacing:-.02em; text-wrap:balance; }}
.lede {{ margin:0; max-width:64ch; color:var(--muted); font-size:16px; }}

.figures {{ display:flex; flex-wrap:wrap; gap:0; margin-top:26px; border:1px solid var(--rule); border-radius:10px; background:var(--surface); overflow:hidden; }}
.fig {{ flex:1 1 130px; padding:14px 18px; border-right:1px solid var(--rule-soft); }}
.fig:last-child {{ border-right:0; }}
.fig b {{ display:block; font-family:var(--font-mono); font-size:22px; font-weight:600; font-variant-numeric:tabular-nums; letter-spacing:-.02em; }}
.fig span {{ font-size:12px; color:var(--subtle); text-transform:uppercase; letter-spacing:.07em; }}

/* ---- layout ---- */
.cols {{ display:grid; grid-template-columns:232px minmax(0,1fr); gap:36px; margin-top:34px; align-items:start; }}
@media (max-width:860px) {{ .cols {{ grid-template-columns:1fr; gap:24px; }} nav.rail {{ position:static !important; max-height:none !important; }} }}

nav.rail {{ position:sticky; top:16px; max-height:calc(100vh - 32px); overflow-y:auto; font-size:13px; }}
nav.rail h2 {{ font-family:var(--font-mono); font-size:11px; letter-spacing:.12em; text-transform:uppercase; color:var(--subtle); margin:0 0 8px; font-weight:600; }}
nav.rail a {{ display:flex; align-items:center; gap:7px; padding:5px 8px; border-radius:6px; color:var(--muted); text-decoration:none; }}
nav.rail a:hover {{ background:var(--sunk); color:var(--ink); }}
nav.rail a em {{ margin-left:auto; font-style:normal; font-family:var(--font-mono); font-size:11px; color:var(--subtle); font-variant-numeric:tabular-nums; }}
.dot {{ width:7px; height:7px; border-radius:50%; flex:0 0 auto; background:var(--muted); }}
.dot.approve {{ background:var(--ok); }}
.dot.needs_revision {{ background:var(--warn); }}
.dot.reject {{ background:var(--bad); }}

/* ---- tables ---- */
.panel {{ background:var(--surface); border:1px solid var(--rule); border-radius:10px; padding:18px 20px; margin-bottom:26px; }}
.panel h3 {{ margin:0 0 12px; font-size:15px; }}
table {{ width:100%; border-collapse:collapse; font-size:13px; }}
td, th {{ padding:5px 8px; text-align:left; border-bottom:1px solid var(--rule-soft); }}
tr:last-child td {{ border-bottom:0; }}
td.num {{ font-family:var(--font-mono); text-align:right; font-variant-numeric:tabular-nums; width:64px; }}
td.bar {{ width:44%; }}
td.bar span {{ display:block; height:7px; border-radius:3px; background:var(--brand-600); min-width:2px; }}
td.bar span.short {{ background:var(--gold); }}

/* ---- generator sections ---- */
.gen {{ margin-bottom:40px; scroll-margin-top:16px; }}
.gen h3 {{ display:flex; align-items:center; gap:9px; font-size:17px; margin:0 0 4px; padding-bottom:8px; border-bottom:1px solid var(--rule); }}
.gen h3 em {{ margin-left:auto; font-style:normal; font-family:var(--font-mono); font-size:11px; color:var(--subtle); letter-spacing:.04em; }}
.cards {{ display:flex; flex-direction:column; gap:14px; margin-top:14px; }}

.card {{ background:var(--surface); border:1px solid var(--rule); border-radius:8px; padding:14px 16px; }}
.card-head {{ display:flex; flex-wrap:wrap; align-items:baseline; gap:8px; margin-bottom:9px; }}
.verdict {{ font-family:var(--font-mono); font-size:10px; font-weight:600; letter-spacing:.09em; text-transform:uppercase; padding:3px 7px; border-radius:4px; }}
.verdict.approve {{ background:var(--ok-soft); color:var(--ok-ink); }}
.verdict.needs_revision {{ background:var(--warn-soft); color:var(--warn-ink); }}
.verdict.reject {{ background:var(--bad-soft); color:var(--bad-ink); }}
.ident {{ font-family:var(--font-mono); font-size:12px; color:var(--brand-600); font-weight:500; }}
.sect {{ font-size:13px; color:var(--muted); }}
.type {{ margin-left:auto; font-size:11px; color:var(--subtle); text-transform:uppercase; letter-spacing:.07em; }}

.chips {{ display:flex; flex-wrap:wrap; gap:5px; margin-bottom:8px; }}
.chip {{ font-family:var(--font-mono); font-size:11px; padding:2px 6px; border-radius:4px; background:var(--sunk); color:var(--muted); }}
.chip.issue {{ background:var(--gold-wash); color:var(--gold-ink); }}
.chip.hard {{ background:var(--brand-wash); color:var(--brand-600); }}
.chip.score {{ background:var(--bad-soft); color:var(--bad-ink); }}
.chip.none {{ opacity:.7; }}

.reason {{ margin:0 0 10px; font-size:13.5px; color:var(--muted); font-style:italic; }}
.reason.none {{ color:var(--bad); font-style:normal; }}

.diff {{ font-family:var(--font-mono); font-size:12.5px; line-height:1.6; background:var(--sunk); border-radius:6px; padding:9px 4px; overflow-x:auto; }}
.line {{ display:block; white-space:pre-wrap; word-break:break-word; padding:1px 10px 1px 6px; }}
.line .sign {{ display:inline-block; width:14px; color:var(--subtle); user-select:none; }}
.line.cut {{ color:var(--bad-ink); }}
.line.add {{ color:var(--ok-ink); }}
mark.cut {{ background:var(--bad-soft); color:var(--bad-ink); text-decoration:line-through; text-decoration-thickness:1px; padding:0 2px; border-radius:2px; }}
mark.add {{ background:var(--ok-soft); color:var(--ok-ink); padding:0 2px; border-radius:2px; }}

.card-foot {{ display:flex; flex-wrap:wrap; gap:14px; margin-top:8px; font-size:11.5px; color:var(--subtle); }}
.notes {{ margin:8px 0 0; padding-left:18px; font-size:12px; color:var(--bad-ink); }}
.gennote {{ margin:8px 0 0; font-size:12px; color:var(--subtle); }}

.chip.strategy {{ background:var(--brand-wash); color:var(--brand-600); }}
.borderline {{ border-left:3px solid var(--gold); padding-left:16px; margin-bottom:44px; }}
.approves {{ border-left:3px solid var(--ok); padding-left:16px; margin-bottom:44px; }}
.approves h2 {{ font-size:20px; margin:0 0 4px; }}
.approves p {{ margin:0 0 14px; color:var(--muted); font-size:14px; max-width:64ch; }}
.borderline h2 {{ font-size:20px; margin:0 0 4px; }}
.borderline p {{ margin:0 0 14px; color:var(--muted); font-size:14px; max-width:64ch; }}
h2.rule {{ font-size:20px; margin:0 0 18px; padding-bottom:9px; border-bottom:2px solid var(--brand); }}
</style>

<div class="wrap">
<header class="top">
  <p class="eyebrow">Checkpoint 4 &middot; context_v2</p>
  <h1>Read these as the admin who has to rule on them</h1>
  <p class="lede">Every example is a whole stored section as the app would submit it, with one
  to three rows or sentences edited. Only the lines that moved are shown; the rest of the
  section is counted under each diff. {per_generator} random examples per generator, plus the ten
  the quality check was least sure about.</p>
  <div class="figures">
    <div class="fig"><b>{total}</b><span>examples</span></div>
    <div class="fig"><b>{approve}</b><span>approve</span></div>
    <div class="fig"><b>{needs}</b><span>needs revision</span></div>
    <div class="fig"><b>{reject}</b><span>reject</span></div>
    <div class="fig"><b>{generators}</b><span>generators</span></div>
    <div class="fig"><b>{documents}</b><span>documents</span></div>
  </div>
</header>

<div class="cols">
  <nav class="rail">
    <h2>Generators</h2>
    {nav}
  </nav>

  <main>
    <div class="panel">
      <h3>Positives per issue label</h3>
      <table><tbody>{label_rows}</tbody></table>
    </div>
    <div class="panel">
      <h3>Section types</h3>
      <table><tbody>{type_rows}</tbody></table>
    </div>

    <section class="borderline">
      <h2>The ten least certain</h2>
      <p>{borderline_total} examples scored below 1.0. These ten scored lowest &mdash; a sentence
      match near the 0.6 cut-off that decides &ldquo;removed&rdquo; from &ldquo;reworded&rdquo;, or a
      hard negative that trips a rule on purpose. If any of these read wrong, the threshold is
      carrying more weight than it should.</p>
      <div class="cards">{borderline}</div>
    </section>

    <section class="approves">
      <h2>Ten approvals, at random</h2>
      <p>Drawn from all {approve_total} approve examples. Each one has to be a change
      a reviewer would wave through: no requirement added, none removed, and a reason
      that matches what the edit actually did.</p>
      <div class="cards">{approve_cards}</div>
    </section>

    <h2 class="rule">By generator</h2>
    {sections}
  </main>
</div>
</div>
"""


if __name__ == "__main__":
    raise SystemExit(main())
