"""Build a clean academic-style PDF of the arXiv paper from its Markdown source.

Pipeline:
    1. Read arxiv-paper-behavioral-drift.md
    2. Convert to HTML with extensions: tables, fenced code, arithmatex (math)
    3. Wrap in academic CSS template (serif, justified, abstract block, refs)
    4. Write standalone HTML
    5. Use Chrome headless to print to PDF

Run:
    python build_arxiv_pdf.py
Outputs:
    arxiv-paper-behavioral-drift.html
    arxiv-paper-behavioral-drift.pdf
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import markdown

HERE = Path(__file__).resolve().parent
MD = HERE / "arxiv-paper-behavioral-drift.md"
HTML = HERE / "arxiv-paper-behavioral-drift.html"
PDF = HERE / "arxiv-paper-behavioral-drift.pdf"

CHROME = r"C:/Program Files/Google/Chrome/Application/chrome.exe"


CSS = r"""
@page { size: A4; margin: 22mm 22mm 26mm 22mm; }

:root {
    --ink: #111;
    --body: #1a1a1a;
    --muted: #555;
    --rule: #222;
    --hairline: #ccc;
    --accent: #1F4068;
    --code-bg: #f5f3ee;
}

* { box-sizing: border-box; margin: 0; padding: 0; }

html, body {
    background: #fff;
    color: var(--body);
    font-family: "Latin Modern Roman", "Computer Modern", "STIX Two Text",
                 "Source Serif Pro", "Cambria", Georgia, serif;
    font-size: 10.5pt;
    line-height: 1.5;
    text-align: justify;
    hyphens: auto;
    -webkit-font-smoothing: antialiased;
    text-rendering: optimizeLegibility;
}

.page-wrap { max-width: 170mm; margin: 0 auto; padding-top: 4mm; }

h1.title {
    font-family: "Latin Modern Roman", Georgia, serif;
    font-weight: 700;
    font-size: 18pt;
    line-height: 1.15;
    text-align: center;
    color: var(--ink);
    margin-bottom: 6mm;
    letter-spacing: -0.005em;
}

.authors {
    text-align: center;
    margin-bottom: 1mm;
    font-size: 11pt;
}
.affil {
    text-align: center;
    margin-bottom: 1mm;
    color: var(--muted);
    font-style: italic;
    font-size: 10pt;
}
.email {
    text-align: center;
    font-family: "Latin Modern Mono", "Consolas", monospace;
    font-size: 9pt;
    color: var(--muted);
    margin-bottom: 6mm;
}

.abstract {
    margin: 8mm 8mm 8mm 8mm;
    padding: 4mm 0;
    border-top: 0.6pt solid var(--rule);
    border-bottom: 0.6pt solid var(--rule);
}
.abstract h2 {
    font-size: 10pt;
    text-align: center;
    text-transform: uppercase;
    letter-spacing: 0.12em;
    margin-bottom: 3mm;
    font-weight: 600;
    border: none;
    padding: 0;
}
.abstract p {
    font-size: 10pt;
    line-height: 1.55;
    text-indent: 0;
}

h2 {
    font-family: "Latin Modern Roman", Georgia, serif;
    font-weight: 700;
    font-size: 12.5pt;
    color: var(--ink);
    margin-top: 8mm;
    margin-bottom: 3mm;
    padding-bottom: 1mm;
    border-bottom: 0.4pt solid var(--hairline);
    page-break-after: avoid;
}

h3 {
    font-family: "Latin Modern Roman", Georgia, serif;
    font-weight: 600;
    font-size: 11pt;
    color: var(--ink);
    margin-top: 5mm;
    margin-bottom: 2mm;
    page-break-after: avoid;
}

p { margin-bottom: 3mm; text-indent: 4mm; }
p:first-of-type, h2 + p, h3 + p, .abstract p { text-indent: 0; }

ul, ol { margin: 0 0 3mm 7mm; padding-left: 3mm; }
li { margin-bottom: 1mm; line-height: 1.55; }

strong { font-weight: 700; }
em { font-style: italic; }

code {
    font-family: "Latin Modern Mono", "JetBrains Mono", "Consolas", monospace;
    font-size: 9.5pt;
    background: var(--code-bg);
    padding: 0 3px;
    border-radius: 2px;
}
pre {
    background: var(--code-bg);
    padding: 3mm;
    border-radius: 2px;
    overflow-x: auto;
    margin-bottom: 3mm;
    font-size: 9pt;
    line-height: 1.4;
}
pre code { background: transparent; padding: 0; }

table {
    width: 100%;
    border-collapse: collapse;
    margin: 4mm 0;
    font-size: 9.5pt;
    page-break-inside: avoid;
}
th, td {
    padding: 4px 8px;
    border-bottom: 0.4pt solid var(--hairline);
    text-align: left;
}
thead th {
    border-top: 0.6pt solid var(--rule);
    border-bottom: 0.6pt solid var(--rule);
    font-weight: 700;
    background: transparent;
}
tbody tr:last-child td { border-bottom: 0.6pt solid var(--rule); }

hr {
    border: none;
    border-top: 0.4pt solid var(--hairline);
    margin: 6mm 0;
}

a { color: var(--accent); text-decoration: none; }
a:hover { text-decoration: underline; }

blockquote {
    margin: 3mm 6mm;
    padding-left: 4mm;
    border-left: 1.2pt solid var(--accent);
    font-style: italic;
    color: var(--muted);
}

/* References section */
h2#references + ul, h2#references + p + ul {
    list-style: none;
    padding-left: 0;
    margin-left: 0;
}

/* Math display blocks */
.arithmatex { font-size: 11pt; }

/* page numbers */
.footer-note {
    margin-top: 8mm;
    text-align: center;
    font-style: italic;
    color: var(--muted);
    font-size: 9pt;
}
"""


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>{title}</title>
<style>{css}</style>
<script>
  window.MathJax = {{
    tex: {{
      inlineMath: [['$', '$'], ['\\\\(', '\\\\)']],
      displayMath: [['$$', '$$'], ['\\\\[', '\\\\]']],
      processEscapes: true,
      processEnvironments: true
    }},
    options: {{
      skipHtmlTags: ['script', 'noscript', 'style', 'textarea', 'pre', 'code']
    }}
  }};
</script>
<script async src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-mml-chtml.js"></script>
</head>
<body>
<div class="page-wrap">
{body}
</div>
</body>
</html>
"""


def main() -> int:
    if not MD.exists():
        print(f"Markdown not found: {MD}", file=sys.stderr)
        return 1

    text = MD.read_text(encoding="utf-8")

    # Split: first line is "# Title", then author block, then "---", then "## Abstract"
    # Extract title and author block manually for cleaner rendering.
    lines = text.splitlines()
    title = lines[0].lstrip("# ").strip()

    # Find the first horizontal rule to split header from body.
    hr_idx = None
    for i, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            hr_idx = i
            break

    # Header block (between title and first ---).
    header_lines = lines[1:hr_idx] if hr_idx else []
    body_md = "\n".join(lines[hr_idx + 1:]) if hr_idx else "\n".join(lines[1:])

    # Parse author block: typically a bold name, an affiliation, an email.
    author = ""
    affil = ""
    email = ""
    for raw in header_lines:
        s = raw.strip()
        if not s:
            continue
        if s.startswith("**") and s.endswith("**"):
            author = s.strip("*").strip()
        elif "@" in s and "." in s:
            email = s
        elif not author:
            author = s
        else:
            affil = s

    # Render body markdown with extensions.
    md = markdown.Markdown(
        extensions=[
            "tables",
            "fenced_code",
            "footnotes",
            "smarty",
            "pymdownx.arithmatex",
        ],
        extension_configs={
            "pymdownx.arithmatex": {"generic": True},
        },
    )
    body_html = md.convert(body_md)

    # Assemble header block.
    header_html = f'<h1 class="title">{title}</h1>\n'
    if author:
        header_html += f'<div class="authors">{author}</div>\n'
    if affil:
        header_html += f'<div class="affil">{affil}</div>\n'
    if email:
        header_html += f'<div class="email">{email}</div>\n'

    # Wrap the abstract specially. The first ## Abstract section becomes a styled block.
    if '<h2>Abstract</h2>' in body_html:
        abstract_open = body_html.find('<h2>Abstract</h2>')
        # Find next <h2> after abstract.
        next_h2 = body_html.find('<h2>', abstract_open + 1)
        if next_h2 == -1:
            next_h2 = len(body_html)
        abstract_block = body_html[abstract_open:next_h2]
        # Replace abstract block with a stylised version.
        wrapped = abstract_block.replace(
            '<h2>Abstract</h2>',
            '<div class="abstract"><h2>Abstract</h2>'
        )
        wrapped += '</div>'
        body_html = (
            body_html[:abstract_open]
            + wrapped
            + body_html[next_h2:]
        )

    full_html = HTML_TEMPLATE.format(
        title=title, css=CSS, body=header_html + body_html,
    )
    HTML.write_text(full_html, encoding="utf-8")
    print(f"wrote {HTML} ({len(full_html):,} bytes)")

    # Now render to PDF via Chrome headless.
    url = HTML.as_uri()
    cmd = [
        CHROME,
        "--headless",
        "--disable-gpu",
        "--no-pdf-header-footer",
        "--no-margins",
        # Give MathJax time to load + render before printing.
        "--virtual-time-budget=15000",
        f"--print-to-pdf={PDF}",
        url,
    ]
    print("running:", " ".join(cmd[:3]), "...", url)
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        print("chrome stderr:", result.stderr[:500], file=sys.stderr)
        return result.returncode
    if PDF.exists():
        size_kb = PDF.stat().st_size // 1024
        print(f"wrote {PDF} ({size_kb} KB)")
        return 0
    print("chrome did not produce a PDF", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
