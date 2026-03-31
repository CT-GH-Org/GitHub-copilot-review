#!/usr/bin/env python3
"""
EDL Code Review Report -- Markdown to HTML Converter

Usage: python3 generate_html_report.py <input.md> [output.html]

Converts EDL code review markdown reports into interactive HTML dashboards.
Supports both First Review and Follow-Up Review formats.
"""
import re
import sys
import os
import html as html_module
from datetime import datetime


# ---------------------------------------------------------------------------
# PARSING
# ---------------------------------------------------------------------------

def _strip_backticks(text):
    """Remove surrounding backtick pairs from inline code."""
    return text.strip().strip('`')


def _extract_code_block(lines, start_idx):
    """Extract a fenced code block starting at start_idx. Returns (code_text, language, end_idx)."""
    first = lines[start_idx]
    m = re.match(r'\s*```(\w*)', first)
    lang = m.group(1) if m else ''
    code_lines = []
    i = start_idx + 1
    while i < len(lines):
        if re.match(r'\s*```\s*$', lines[i]):
            return '\n'.join(code_lines), lang, i
        code_lines.append(lines[i])
        i += 1
    return '\n'.join(code_lines), lang, i


def _parse_issue_block(lines, start_idx, severity):
    """Parse a single numbered issue block. Returns (issue_dict, end_idx)."""
    first_line = lines[start_idx]
    # Pattern: N. **[Category]** `file:line` -- Description  (or with em-dash)
    m = re.match(
        r'\s*(\d+)\.\s+\*\*\[([^\]]+)\]\*\*\s+`([^`]+)`\s*(?:--|-{1,3}|\\u2014)\s*(.*)',
        first_line
    )
    if not m:
        # Try alternate: description may not have file ref
        m = re.match(r'\s*(\d+)\.\s+\*\*\[([^\]]+)\]\*\*\s+(.*)', first_line)
        if not m:
            return None, start_idx + 1
        issue = {
            'number': int(m.group(1)),
            'category': m.group(2).strip(),
            'file': '',
            'description': m.group(3).strip().lstrip('`').rstrip('`'),
            'severity': severity,
            'current': '',
            'required': '',
            'reference': '',
            'code_snippet': '',
            'code_lang': '',
            'suggested_fix': '',
            'fix_lang': '',
        }
    else:
        issue = {
            'number': int(m.group(1)),
            'category': m.group(2).strip(),
            'file': m.group(3).strip(),
            'description': m.group(4).strip(),
            'severity': severity,
            'current': '',
            'required': '',
            'reference': '',
            'code_snippet': '',
            'code_lang': '',
            'suggested_fix': '',
            'fix_lang': '',
        }

    # Also capture status for follow-up reviews
    issue['status'] = ''  # '', 'STILL OPEN', 'NEW'

    i = start_idx + 1
    current_field = None
    field_lines = []

    def flush_field():
        nonlocal current_field, field_lines
        if current_field and field_lines:
            text = '\n'.join(field_lines).strip()
            if current_field == 'current':
                issue['current'] = text
            elif current_field == 'required':
                issue['required'] = text
            elif current_field == 'reference':
                issue['reference'] = text
        field_lines = []

    while i < len(lines):
        line = lines[i]
        # Check if we hit the next numbered issue or section header
        if re.match(r'\s*\d+\.\s+\*\*\[', line):
            break
        if re.match(r'^---\s*$', line):
            break
        if re.match(r'^##\s+', line):
            break

        # Detect sub-fields
        if re.match(r'\s+- \*\*Current:\*\*\s*(.*)', line, re.IGNORECASE):
            flush_field()
            current_field = 'current'
            field_lines = [re.match(r'\s+- \*\*Current:\*\*\s*(.*)', line, re.IGNORECASE).group(1)]
            i += 1
            continue
        elif re.match(r'\s+- \*\*Required:\*\*\s*(.*)', line, re.IGNORECASE):
            flush_field()
            current_field = 'required'
            field_lines = [re.match(r'\s+- \*\*Required:\*\*\s*(.*)', line, re.IGNORECASE).group(1)]
            i += 1
            continue
        elif re.match(r'\s+- \*\*Reference:\*\*\s*(.*)', line, re.IGNORECASE):
            flush_field()
            current_field = 'reference'
            field_lines = [re.match(r'\s+- \*\*Reference:\*\*\s*(.*)', line, re.IGNORECASE).group(1)]
            i += 1
            continue
        elif re.match(r'\s+- \*\*Code Snippet:\*\*', line, re.IGNORECASE):
            flush_field()
            current_field = None
            # Next should be a code block
            i += 1
            while i < len(lines) and lines[i].strip() == '':
                i += 1
            if i < len(lines) and re.match(r'\s*```', lines[i]):
                code, lang, end = _extract_code_block(lines, i)
                issue['code_snippet'] = code
                issue['code_lang'] = lang
                i = end + 1
            continue
        elif re.match(r'\s+- \*\*Suggested Fix:\*\*', line, re.IGNORECASE):
            flush_field()
            current_field = None
            i += 1
            while i < len(lines) and lines[i].strip() == '':
                i += 1
            if i < len(lines) and re.match(r'\s*```', lines[i]):
                code, lang, end = _extract_code_block(lines, i)
                issue['suggested_fix'] = code
                issue['fix_lang'] = lang
                i = end + 1
            continue
        elif re.match(r'\s+- \*\*Status:', line, re.IGNORECASE):
            sm = re.search(r'STILL\s+OPEN', line, re.IGNORECASE)
            if sm:
                issue['status'] = 'STILL OPEN'
            elif re.search(r'NEW', line, re.IGNORECASE):
                issue['status'] = 'NEW'
            i += 1
            continue

        # Continuation of current field
        if current_field:
            stripped = line.strip()
            if stripped:
                field_lines.append(stripped)
            elif field_lines:
                # Blank line ends field unless within multi-line
                pass

        i += 1

    flush_field()

    # Clean up description -- remove trailing em-dash content
    desc = issue['description']
    desc = re.sub(r'\s*—\s*$', '', desc)
    issue['description'] = desc.rstrip()

    return issue, i


def _parse_table(lines, start_idx):
    """Parse a markdown table. Returns (list_of_row_dicts, end_idx) or (list_of_row_lists, end_idx)."""
    # Find header
    i = start_idx
    while i < len(lines) and not re.match(r'\s*\|', lines[i]):
        i += 1
    if i >= len(lines):
        return [], i

    header_line = lines[i]
    headers = [h.strip() for h in header_line.strip().strip('|').split('|')]
    i += 1
    # Skip separator line
    if i < len(lines) and re.match(r'\s*\|[-|: ]+\|', lines[i]):
        i += 1

    rows = []
    while i < len(lines):
        line = lines[i].strip()
        if not line.startswith('|'):
            break
        cells = [c.strip() for c in line.strip('|').split('|')]
        row = {}
        for j, h in enumerate(headers):
            row[h] = cells[j] if j < len(cells) else ''
        rows.append(row)
        i += 1

    return rows, i


def parse_md_report(md_content):
    """Parse markdown report into structured data."""
    data = {
        'is_followup': False,
        'title': 'EDL Code Review Report',
        'files_reviewed': [],
        'review_date': '',
        'agents': [],
        'review_type': 'First Review',
        'previous_review': '',
        'exec_summary': {
            'total': 0,
            'critical': 0,
            'major': 0,
            'medium': 0,
            'minor': 0,
            'recommendation': '',
            'paragraph': '',
        },
        'issues': {
            'critical': [],
            'major': [],
            'medium': [],
            'minor': [],
        },
        'per_file_breakdown': [],
        'what_passed': [],
        'checklist': [],
        'summary_text': '',
        'priority_remediation': [],
        # Follow-up specific
        'progress_summary': {},
        'resolved_issues': [],
        'still_open_issues': [],
        'new_issues': [],
        'trend_analysis': [],
        'checklist_followup': [],
    }

    lines = md_content.split('\n')
    n = len(lines)

    # Detect follow-up review
    if 'Follow-Up Review' in md_content or 'Follow-Up' in md_content:
        for line in lines[:10]:
            if 'Follow-Up' in line:
                data['is_followup'] = True
                data['title'] = 'EDL Code Review Report -- Follow-Up Review'
                break

    # Parse header metadata
    for line in lines:
        if line.startswith('- `') and '/' in line:
            data['files_reviewed'].append(_strip_backticks(line.lstrip('- ')))
        m = re.match(r'\*\*Review Date:\*\*\s*(.*)', line)
        if m:
            data['review_date'] = m.group(1).strip()
        m = re.match(r'\*\*Agents Used:\*\*\s*(.*)', line)
        if m:
            data['agents'] = [a.strip() for a in m.group(1).split(',')]
        m = re.match(r'\*\*Review Type:\*\*\s*(.*)', line)
        if m:
            data['review_type'] = m.group(1).strip()
        m = re.match(r'\*\*Previous Review:\*\*\s*(.*)', line)
        if m:
            data['previous_review'] = m.group(1).strip()

    # Parse executive summary section
    i = 0
    while i < n:
        if re.match(r'^##\s+Executive Summary', lines[i]):
            i += 1
            summary_lines = []
            while i < n and not re.match(r'^---', lines[i]) and not re.match(r'^##\s+', lines[i]):
                line = lines[i].strip()
                if line.startswith('- **Total Issues:**'):
                    m = re.search(r'(\d+)\s*\((\d+)\s+Critical.*?(\d+)\s+Major.*?(\d+)\s+Medium.*?(\d+)\s+Minor\)', line)
                    if m:
                        data['exec_summary']['total'] = int(m.group(1))
                        data['exec_summary']['critical'] = int(m.group(2))
                        data['exec_summary']['major'] = int(m.group(3))
                        data['exec_summary']['medium'] = int(m.group(4))
                        data['exec_summary']['minor'] = int(m.group(5))
                elif line.startswith('- **Recommendation:**'):
                    data['exec_summary']['recommendation'] = line.split(':**')[1].strip() if ':**' in line else ''
                elif line.startswith('- ') and not line.startswith('- **'):
                    summary_lines.append(line[2:])
                elif line and not line.startswith('- **'):
                    summary_lines.append(line)
                i += 1
            data['exec_summary']['paragraph'] = ' '.join(summary_lines).strip()
            break
        i += 1

    # Parse issues by severity section
    severity_headers = {
        r'^##\s+Critical Issues': 'critical',
        r'^##\s+Major Issues': 'major',
        r'^##\s+Medium Issues': 'medium',
        r'^##\s+Minor Issues': 'minor',
    }

    for pattern, severity in severity_headers.items():
        i = 0
        while i < n:
            if re.match(pattern, lines[i]):
                i += 1
                # Skip description lines until first numbered issue
                while i < n and not re.match(r'\s*\d+\.\s+\*\*\[', lines[i]):
                    if re.match(r'^---', lines[i]) or re.match(r'^##\s+', lines[i]):
                        break
                    i += 1
                # Parse issues
                while i < n:
                    if re.match(r'^---', lines[i]) or (re.match(r'^##\s+', lines[i]) and not re.match(r'^##\s+(Critical|Major|Medium|Minor)', lines[i])):
                        break
                    if re.match(r'\s*\d+\.\s+\*\*\[', lines[i]):
                        issue, i = _parse_issue_block(lines, i, severity)
                        if issue:
                            data['issues'][severity].append(issue)
                    else:
                        i += 1
                break
            i += 1

    # Follow-up: parse Still Open, New Issues, Resolved sections
    if data['is_followup']:
        # Parse resolved issues table
        i = 0
        while i < n:
            if re.match(r'^###?\s+Resolved Issues', lines[i], re.IGNORECASE):
                i += 1
                rows, i = _parse_table(lines, i)
                data['resolved_issues'] = rows
                break
            i += 1

        # Parse Still Open and New Issues sections similarly to normal issues
        still_open_headers = {
            r'^###?\s+Still Open Issues': True,
        }
        new_issue_headers = {
            r'^###?\s+New Issues': True,
        }

        # Parse progress summary table
        i = 0
        while i < n:
            if re.match(r'^##\s+Progress Summary', lines[i], re.IGNORECASE) or \
               re.match(r'^##\s+Executive Summary', lines[i], re.IGNORECASE):
                i += 1
                # Look for the metrics table
                rows, end = _parse_table(lines, i)
                if rows:
                    for row in rows:
                        metric = row.get('Metric', row.get(list(row.keys())[0] if row else '', ''))
                        value = row.get('Value', row.get(list(row.keys())[1] if len(row) > 1 else '', ''))
                        data['progress_summary'][metric.strip()] = value.strip()
                break
            i += 1

        # Parse trend analysis table
        i = 0
        while i < n:
            if re.match(r'^##\s+Trend Analysis', lines[i], re.IGNORECASE):
                i += 1
                rows, end = _parse_table(lines, i)
                data['trend_analysis'] = rows
                break
            i += 1

    # Parse Per-File Breakdown table
    i = 0
    while i < n:
        if re.match(r'^##\s+Per-File Breakdown', lines[i]):
            i += 1
            rows, end = _parse_table(lines, i)
            data['per_file_breakdown'] = rows
            break
        i += 1

    # Parse What Passed
    i = 0
    while i < n:
        if re.match(r'^##\s+What Passed', lines[i]):
            i += 1
            while i < n and not re.match(r'^---', lines[i]) and not re.match(r'^##\s+', lines[i]):
                line = lines[i].strip()
                if line.startswith('- '):
                    data['what_passed'].append(line[2:].strip())
                i += 1
            break
        i += 1

    # Parse Review Checklist Status table
    i = 0
    while i < n:
        if re.match(r'^##\s+Review Checklist Status', lines[i]):
            i += 1
            rows, end = _parse_table(lines, i)
            data['checklist'] = rows
            break
        i += 1

    # Parse Summary section
    i = 0
    while i < n:
        if re.match(r'^##\s+Summary', lines[i]):
            i += 1
            summary_parts = []
            prio_started = False
            while i < n:
                line = lines[i].strip()
                if re.match(r'^---', line) or re.match(r'^##\s+', line):
                    break
                if line.startswith('**Priority remediation order:**') or line.startswith('**Priority remediation'):
                    prio_started = True
                    i += 1
                    continue
                if prio_started:
                    m = re.match(r'\d+\.\s+\*\*\[([^\]]+)\]\*\*\s+(.*)', line)
                    if m:
                        data['priority_remediation'].append({
                            'severity': m.group(1).strip().lower(),
                            'text': m.group(2).strip(),
                        })
                else:
                    if line.startswith('- **Total Issues:**'):
                        pass  # Already parsed
                    elif line.startswith('- **Recommendation:**'):
                        pass  # Already parsed
                    elif line and not line.startswith('- **'):
                        summary_parts.append(line)
                i += 1
            data['summary_text'] = '\n'.join(summary_parts).strip()
            break
        i += 1

    # If summary_text is empty, try to reconstruct from exec_summary
    if not data['summary_text'] and data['exec_summary']['paragraph']:
        data['summary_text'] = data['exec_summary']['paragraph']

    return data


# ---------------------------------------------------------------------------
# HTML GENERATION
# ---------------------------------------------------------------------------

def _esc(text):
    """HTML-escape text."""
    return html_module.escape(str(text))


def _md_inline_to_html(text):
    """Convert limited markdown inline formatting to HTML."""
    if not text:
        return ''
    # Escape HTML first
    t = _esc(text)
    # Bold
    t = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', t)
    # Inline code
    t = re.sub(r'`([^`]+)`', r'<code>\1</code>', t)
    # Em-dash
    t = t.replace(' -- ', ' &mdash; ')
    t = t.replace('--', '&mdash;')
    return t


def _severity_lower(s):
    """Normalize severity to lowercase."""
    return s.strip().lower().replace('still open — ', '').replace('still open - ', '').replace('new — ', '').replace('new - ', '')


def _ref_tags_html(ref_text):
    """Convert reference text into ref-tag spans."""
    if not ref_text:
        return ''
    # Split on semicolons or common delimiters
    parts = re.split(r';\s*', ref_text)
    tags = []
    for p in parts:
        p = p.strip()
        if not p:
            continue
        # Also split on ' — ' or ' -- '
        for sub in re.split(r'\s*(?:—|--)\s*', p):
            sub = sub.strip().strip('`').strip('*').strip()
            if sub:
                tags.append(f'<span class="ref-tag">{_esc(sub)}</span>')
    return ''.join(tags)


def _code_block_html(code, label='Current', is_fix=False):
    """Generate HTML for a code block with copy button."""
    if not code:
        return ''
    label_class = 'code-label fix' if is_fix else 'code-label'
    label_text = 'Fix' if is_fix else label
    escaped = _esc(code)
    return f'''<div class="code-wrap">
              <span class="{label_class}">{label_text}</span>
              <button class="copy-btn" onclick="copyCode(this)">Copy</button>
              <pre class="code-block">{escaped}</pre>
            </div>'''


def _issue_card_html(issue):
    """Generate HTML for a single issue card."""
    sev = issue['severity']
    num = issue['number']
    cat = _esc(issue['category'])
    file_ref = _esc(issue['file'])
    desc = _esc(issue['description'])
    data_text = f"{cat.lower()} {file_ref.lower()} {desc.lower()}"

    status_badge = ''
    if issue.get('status') == 'STILL OPEN':
        status_badge = ' <span style="font-size:0.7em;padding:2px 8px;border-radius:10px;background:var(--orange-l);color:var(--orange);font-weight:700">STILL OPEN</span>'
    elif issue.get('status') == 'NEW':
        status_badge = ' <span style="font-size:0.7em;padding:2px 8px;border-radius:10px;background:var(--purple-l);color:var(--purple);font-weight:700">NEW</span>'

    body_parts = []

    # Current
    if issue['current']:
        body_parts.append(f'''<div class="issue-section">
            <div class="issue-section-label current">Current</div>
            <div class="issue-current">{_md_inline_to_html(issue['current'])}</div>
          </div>''')

    # Required
    if issue['required']:
        body_parts.append(f'''<div class="issue-section">
            <div class="issue-section-label required">Required</div>
            <div class="issue-required">{_md_inline_to_html(issue['required'])}</div>
          </div>''')

    # Reference
    if issue['reference']:
        body_parts.append(f'''<div class="issue-section">
            <div class="issue-section-label reference">Reference</div>
            <div>{_ref_tags_html(issue['reference'])}</div>
          </div>''')

    # Code Snippet
    if issue['code_snippet']:
        body_parts.append(f'''<div class="issue-section">
            <div class="issue-section-label current">Code Snippet</div>
            {_code_block_html(issue['code_snippet'], 'Current', False)}
          </div>''')

    # Suggested Fix
    if issue['suggested_fix']:
        body_parts.append(f'''<div class="issue-section">
            <div class="issue-section-label required">Suggested Fix</div>
            {_code_block_html(issue['suggested_fix'], 'Fix', True)}
          </div>''')

    file_html = f'<span class="issue-file">{file_ref}</span>' if file_ref else ''

    return f'''<div class="issue-card {sev}" data-severity="{sev}" data-text="{_esc(data_text)}">
        <div class="issue-header" onclick="toggleIssue(this)">
          <span class="issue-num">#{num}</span>
          <span class="issue-cat {sev}">{cat}</span>
          {file_html}
          <span class="issue-desc">{desc}{status_badge}</span>
          <span class="issue-toggle">&#9660;</span>
        </div>
        <div class="issue-body">
          {''.join(body_parts)}
        </div>
      </div>'''


def _breakdown_row_html(row, is_total=False):
    """Generate a table row for per-file breakdown."""
    keys = list(row.keys())
    file_val = row.get('File', row.get(keys[0], '')) if keys else ''
    file_val = file_val.strip().strip('`')

    def get_int(key_name):
        for k in row:
            if k.strip().lower() == key_name.lower():
                v = row[k].strip().strip('*')
                try:
                    return int(v)
                except ValueError:
                    return 0
        return 0

    critical = get_int('Critical')
    major = get_int('Major')
    medium = get_int('Medium')
    minor = get_int('Minor')
    total = get_int('Total')

    if is_total:
        return f'''<tr class="total-row">
          <td style="font-weight:800">{_esc(file_val)}</td>
          <td class="cell-critical">{critical}</td>
          <td class="cell-major">{major}</td>
          <td class="cell-medium">{medium}</td>
          <td class="cell-minor">{minor}</td>
          <td style="text-align:center;font-weight:900;font-size:1.1em">{total}</td>
        </tr>'''

    def cell_class(val, severity):
        if val == 0:
            return 'cell-zero'
        return f'cell-{severity}'

    is_highlight = total >= 5
    is_clean = total == 0
    file_style = ' style="color:var(--green)"' if is_clean else ''
    row_class = ' class="highlight-row"' if is_highlight else ''

    total_style = 'text-align:center;font-weight:800' if total >= 5 else 'text-align:center;font-weight:700'
    total_class = 'cell-zero' if total == 0 else ''

    return f'''<tr{row_class}>
          <td class="cell-file"{file_style}>{_esc(file_val)}</td>
          <td class="{cell_class(critical, 'critical')}">{critical}</td>
          <td class="{cell_class(major, 'major')}">{major}</td>
          <td class="{cell_class(medium, 'medium')}">{medium}</td>
          <td class="{cell_class(minor, 'minor')}">{minor}</td>
          <td class="{total_class}" style="{total_style}">{total}</td>
        </tr>'''


def _get_rec_badge_class(recommendation):
    """Get CSS class for recommendation badge."""
    rec = recommendation.upper()
    if 'REWORK' in rec:
        return 'rework'
    elif 'APPROVE WITH' in rec:
        return 'approve-changes'
    elif 'APPROVE' in rec:
        return 'approve'
    return 'rework'


def _group_files_by_type(files):
    """Group files into categories based on naming patterns."""
    groups = {}
    type_map = [
        ('Pipelines', lambda f: '/pipeline/' in f or os.path.basename(f).startswith('pl_')),
        ('Linked Services', lambda f: '/linkedService/' in f or os.path.basename(f).startswith('ls_')),
        ('Datasets', lambda f: '/dataset/' in f or os.path.basename(f).startswith('ds_')),
        ('Integration Runtimes', lambda f: '/integrationRuntime/' in f or os.path.basename(f).startswith('ir_')),
        ('Triggers', lambda f: '/trigger/' in f or os.path.basename(f).startswith('tr_')),
        ('Notebooks', lambda f: f.endswith('.py') or f.endswith('.ipynb') or '/notebook/' in f.lower()),
        ('SQL', lambda f: f.endswith('.sql')),
        ('ARM Parameters', lambda f: 'arm_template' in f.lower()),
        ('Other', lambda f: True),
    ]

    for filepath in files:
        placed = False
        for group_name, test_fn in type_map:
            if test_fn(filepath):
                if group_name not in groups:
                    groups[group_name] = []
                groups[group_name].append(os.path.basename(filepath))
                placed = True
                break
        if not placed:
            groups.setdefault('Other', []).append(os.path.basename(filepath))

    return groups


def generate_html(data):
    """Generate complete HTML string from parsed data."""
    es = data['exec_summary']
    total = es['total']
    critical = es['critical']
    major = es['major']
    medium = es['medium']
    minor = es['minor']
    recommendation = es['recommendation']
    rec_class = _get_rec_badge_class(recommendation)
    review_date = data['review_date']
    review_type = data['review_type']
    agents = data['agents']
    is_followup = data['is_followup']

    all_issues = []
    for sev in ['critical', 'major', 'medium', 'minor']:
        all_issues.extend(data['issues'][sev])

    # File groups
    file_groups = _group_files_by_type(data['files_reviewed'])
    file_count = len(data['files_reviewed'])

    # Checklist pass/fail count
    pass_count = 0
    fail_count = 0
    for row in data['checklist']:
        status_val = ''
        for k, v in row.items():
            if k.strip().lower() == 'status':
                status_val = v
                break
        if 'PASS' in status_val.upper():
            pass_count += 1
        elif 'FAIL' in status_val.upper():
            fail_count += 1

    # Agent badges
    agent_badges = ''.join(
        f'<span class="top-badge agent">{_esc(a)}</span>' for a in agents
    )

    # Type badge class
    type_class = 'type-first'
    if is_followup:
        type_class = 'type-first'  # same style, could customize

    # Previous review badge for follow-up
    prev_badge = ''
    if data['previous_review']:
        prev_badge = f'<span class="top-badge" style="background:var(--gold-l);color:var(--gold);border-color:rgba(217,119,6,0.15)">Prev: {_esc(data["previous_review"])}</span>'

    # Build file chips HTML
    file_chips_html = ''
    for group_name, file_list in file_groups.items():
        chips = ''.join(f'<span class="file-chip">{_esc(f)}</span>' for f in file_list)
        file_chips_html += f'''<div class="file-group">
      <div class="file-group-label">{_esc(group_name)} ({len(file_list)})</div>
      <div class="file-chips">{chips}</div>
    </div>'''

    # Build issue tabs HTML
    def build_issue_tab(severity, issues_list):
        cards = '\n'.join(_issue_card_html(issue) for issue in issues_list)
        return cards

    critical_cards = build_issue_tab('critical', data['issues']['critical'])
    major_cards = build_issue_tab('major', data['issues']['major'])
    medium_cards = build_issue_tab('medium', data['issues']['medium'])
    minor_cards = build_issue_tab('minor', data['issues']['minor'])

    # Determine which tab is visible by default
    default_tab = 'critical'
    if not data['issues']['critical']:
        if data['issues']['major']:
            default_tab = 'major'
        elif data['issues']['medium']:
            default_tab = 'medium'
        elif data['issues']['minor']:
            default_tab = 'minor'

    tab_classes = {
        'critical': 'on' if default_tab == 'critical' else '',
        'major': 'on' if default_tab == 'major' else '',
        'medium': 'on' if default_tab == 'medium' else '',
        'minor': 'on' if default_tab == 'minor' else '',
    }
    pane_classes = {
        'critical': 'vis' if default_tab == 'critical' else '',
        'major': 'vis' if default_tab == 'major' else '',
        'medium': 'vis' if default_tab == 'medium' else '',
        'minor': 'vis' if default_tab == 'minor' else '',
    }

    # Per-file breakdown rows
    breakdown_rows = ''
    for row in data['per_file_breakdown']:
        file_val = ''
        for k in row:
            if k.strip().lower() == 'file':
                file_val = row[k]
                break
            if not file_val:
                file_val = row[list(row.keys())[0]] if row else ''
        is_total = file_val.strip().startswith('**Total') or file_val.strip().lower() == 'total'
        breakdown_rows += _breakdown_row_html(row, is_total)

    # What passed cards
    passed_html = ''
    for item in data['what_passed']:
        passed_html += f'<div class="pass-card"><span class="pass-icon">&#10003;</span><span class="pass-text">{_md_inline_to_html(item)}</span></div>\n'

    # Checklist rows
    checklist_html = ''
    for row in data['checklist']:
        keys = list(row.keys())
        num = row.get('#', row.get(keys[0], '')) if keys else ''
        category = row.get('Category', row.get(keys[1] if len(keys) > 1 else '', ''))
        status = row.get('Status', row.get(keys[2] if len(keys) > 2 else '', ''))
        notes = row.get('Notes', row.get(keys[3] if len(keys) > 3 else '', ''))

        # Clean markdown bold from status
        status_clean = status.replace('**', '').strip()
        if 'PASS' in status_clean.upper():
            status_html = '<span class="check-badge pass">&#10003; PASS</span>'
        else:
            status_html = '<span class="check-badge fail">&#10007; FAIL</span>'

        # For follow-up reviews with Previous/Current/Trend columns
        if is_followup:
            previous = row.get('Previous', '')
            current_status = row.get('Current', status)
            trend = row.get('Trend', '')
            notes = row.get('Notes', row.get(keys[-1] if keys else '', ''))

            current_clean = current_status.replace('**', '').strip()
            if 'PASS' in current_clean.upper():
                current_html = '<span class="check-badge pass">&#10003; PASS</span>'
            else:
                current_html = '<span class="check-badge fail">&#10007; FAIL</span>'

            prev_clean = previous.replace('**', '').strip()
            if 'PASS' in prev_clean.upper():
                prev_html = '<span class="check-badge pass">&#10003; PASS</span>'
            elif 'FAIL' in prev_clean.upper():
                prev_html = '<span class="check-badge fail">&#10007; FAIL</span>'
            else:
                prev_html = _esc(prev_clean)

            trend_clean = trend.replace('**', '').strip()
            trend_html = _esc(trend_clean)
            if 'FIXED' in trend_clean.upper():
                trend_html = '<span style="color:var(--green);font-weight:700">FIXED</span>'
            elif trend_clean == '--' or trend_clean == '—':
                trend_html = '<span style="color:var(--text-m)">--</span>'

            checklist_html += f'''<tr>
              <td>{_esc(num.strip())}</td>
              <td style="font-weight:600">{_md_inline_to_html(category)}</td>
              <td>{prev_html}</td>
              <td>{current_html}</td>
              <td>{trend_html}</td>
              <td class="check-notes">{_md_inline_to_html(notes)}</td>
            </tr>'''
        else:
            checklist_html += f'''<tr>
              <td>{_esc(num.strip())}</td>
              <td style="font-weight:600">{_md_inline_to_html(category)}</td>
              <td>{status_html}</td>
              <td class="check-notes">{_md_inline_to_html(notes)}</td>
            </tr>'''

    # Checklist table header
    if is_followup and data['checklist'] and any('Previous' in row or 'Trend' in row for row in data['checklist']):
        checklist_header = '<tr><th>#</th><th>Category</th><th>Previous</th><th>Current</th><th>Trend</th><th>Notes</th></tr>'
    else:
        checklist_header = '<tr><th>#</th><th>Category</th><th>Status</th><th>Notes</th></tr>'

    # Priority remediation cards
    prio_html = ''
    for idx, item in enumerate(data['priority_remediation'], 1):
        sev = _severity_lower(item['severity'])
        if sev not in ('critical', 'major', 'medium', 'minor'):
            # Handle "still open — critical" etc
            for s in ('critical', 'major', 'medium', 'minor'):
                if s in item['severity'].lower():
                    sev = s
                    break
            else:
                sev = 'medium'

        sev_colors = {
            'critical': ('var(--red-l)', 'var(--red)'),
            'major': ('var(--orange-l)', 'var(--orange)'),
            'medium': ('var(--cyan-l)', 'var(--cyan)'),
            'minor': ('var(--slate-l)', 'var(--slate)'),
        }
        bg, fg = sev_colors.get(sev, sev_colors['medium'])
        label = item['severity'].strip().title()

        prio_html += f'''<div class="prio-card {sev}">
      <div class="prio-num">{idx}</div>
      <div>
        <span class="prio-sev" style="background:{bg};color:{fg}">{_esc(label)}</span>
        <div class="prio-desc">{_md_inline_to_html(item['text'])}</div>
      </div>
    </div>\n'''

    # Summary text
    summary_paragraph = _md_inline_to_html(data['summary_text'])

    # Follow-up specific sections
    followup_sections = ''
    if is_followup:
        # Progress Summary section
        if data['progress_summary']:
            ps = data['progress_summary']
            progress_rows = ''
            for metric, value in ps.items():
                progress_rows += f'<tr><td style="font-weight:600">{_esc(metric)}</td><td>{_md_inline_to_html(value)}</td></tr>'
            followup_sections += f'''
<section id="progress-section">
<div class="sec reveal">
  <div class="sec-head" onclick="toggleSection(this)">
    <div class="sec-ico" style="background:var(--purple-l);color:var(--purple)">
      <svg width="18" height="18" fill="none" stroke="currentColor" stroke-width="2"><polyline points="2,14 6,8 10,11 16,4"/><circle cx="16" cy="4" r="1.5"/></svg>
    </div>
    <div class="sec-title">Progress Summary</div>
    <span class="sec-chev">&#9660;</span>
  </div>
  <div class="sec-body">
    <div style="overflow-x:auto">
    <table>
      <thead><tr><th>Metric</th><th>Value</th></tr></thead>
      <tbody>{progress_rows}</tbody>
    </table>
    </div>
  </div>
</div>
</section>
'''

        # Resolved Issues section
        if data['resolved_issues']:
            resolved_rows = ''
            for row in data['resolved_issues']:
                cells = list(row.values())
                resolved_rows += '<tr>' + ''.join(f'<td>{_md_inline_to_html(c)}</td>' for c in cells) + '</tr>'
            resolved_headers = ''.join(f'<th>{_esc(k)}</th>' for k in data['resolved_issues'][0].keys())
            followup_sections += f'''
<section id="resolved-section">
<div class="sec reveal">
  <div class="sec-head" onclick="toggleSection(this)">
    <div class="sec-ico" style="background:var(--green-l);color:var(--green)">
      <svg width="18" height="18" fill="none" stroke="currentColor" stroke-width="2"><polyline points="4,9 7,12 14,5"/></svg>
    </div>
    <div class="sec-title">Resolved Issues <span class="sec-badge" style="background:var(--green-l);color:var(--green)">{len(data['resolved_issues'])} resolved</span></div>
    <span class="sec-chev">&#9660;</span>
  </div>
  <div class="sec-body">
    <div style="overflow-x:auto">
    <table>
      <thead><tr>{resolved_headers}</tr></thead>
      <tbody>{resolved_rows}</tbody>
    </table>
    </div>
  </div>
</div>
</section>
'''

        # Trend Analysis section
        if data['trend_analysis']:
            trend_rows = ''
            for row in data['trend_analysis']:
                cells = list(row.values())
                trend_rows += '<tr>' + ''.join(f'<td>{_md_inline_to_html(c)}</td>' for c in cells) + '</tr>'
            trend_headers = ''.join(f'<th>{_esc(k)}</th>' for k in data['trend_analysis'][0].keys())
            followup_sections += f'''
<section id="trend-section">
<div class="sec reveal">
  <div class="sec-head" onclick="toggleSection(this)">
    <div class="sec-ico" style="background:var(--neon-l);color:var(--neon)">
      <svg width="18" height="18" fill="none" stroke="currentColor" stroke-width="2"><polyline points="2,14 6,8 10,11 16,4"/><circle cx="16" cy="4" r="1.5"/></svg>
    </div>
    <div class="sec-title">Trend Analysis</div>
    <span class="sec-chev">&#9660;</span>
  </div>
  <div class="sec-body">
    <div style="overflow-x:auto">
    <table>
      <thead><tr>{trend_headers}</tr></thead>
      <tbody>{trend_rows}</tbody>
    </table>
    </div>
  </div>
</div>
</section>
'''

    # Follow-up sidebar nav items
    followup_nav = ''
    if is_followup:
        if data['progress_summary']:
            followup_nav += '''<div class="nav-item" onclick="scrollToSection('progress-section')">
    <svg width="18" height="18" fill="none" stroke="currentColor" stroke-width="2"><polyline points="2,14 6,8 10,11 16,4"/><circle cx="16" cy="4" r="1.5"/></svg>
    <span class="tooltip">Progress</span>
  </div>'''
        if data['resolved_issues']:
            followup_nav += '''<div class="nav-item" onclick="scrollToSection('resolved-section')">
    <svg width="18" height="18" fill="none" stroke="currentColor" stroke-width="2"><polyline points="4,9 7,12 14,5"/></svg>
    <span class="tooltip">Resolved</span>
  </div>'''
        if data['trend_analysis']:
            followup_nav += '''<div class="nav-item" onclick="scrollToSection('trend-section')">
    <svg width="18" height="18" fill="none" stroke="currentColor" stroke-width="2"><polyline points="2,14 6,8 10,11 16,4"/><circle cx="16" cy="4" r="1.5"/></svg>
    <span class="tooltip">Trends</span>
  </div>'''

    # Build additional sidebar section IDs for scroll spy
    followup_section_ids = ''
    if is_followup:
        if data['progress_summary']:
            followup_section_ids += ",'progress-section'"
        if data['resolved_issues']:
            followup_section_ids += ",'resolved-section'"
        if data['trend_analysis']:
            followup_section_ids += ",'trend-section'"

    # Generation timestamp
    try:
        now = datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
    except AttributeError:
        # Python < 3.11 fallback
        from datetime import timezone
        now = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')

    # Build the complete HTML
    html = f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>EDL Code Review Report | {_esc(review_type)} {_esc(review_date)}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800;900&family=JetBrains+Mono:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
*,*::before,*::after{{margin:0;padding:0;box-sizing:border-box}}
:root {{
  --bg: #f8f9fc; --bg2: #f1f3f8; --bg-card: #ffffff;
  --bg-subtle: #f4f5f9; --bg-glass: rgba(255,255,255,0.85);
  --border: #e5e7ef; --border-glow: rgba(79,70,229,0.12);
  --border-hover: #c7cde0;
  --text-h: #1e293b; --text-p: #475569; --text-s: #64748b; --text-m: #94a3b8;
  --neon: #4f46e5; --neon-l: #eef2ff; --neon-d: #3730a3;
  --cyan: #0891b2; --cyan-l: #ecfeff;
  --green: #059669; --green-l: #ecfdf5;
  --orange: #ea580c; --orange-l: #fff7ed;
  --red: #dc2626; --red-l: #fef2f2;
  --purple: #7c3aed; --purple-l: #f5f3ff;
  --slate: #64748b; --slate-l: #f1f5f9;
  --gold: #d97706; --gold-l: #fffbeb;
  --grad: linear-gradient(135deg, #4f46e5, #7c3aed);
  --r-sm: 8px; --r-md: 12px; --r-lg: 16px; --r-xl: 20px;
  --sh-sm: 0 1px 3px rgba(0,0,0,0.04);
  --sh-md: 0 4px 12px rgba(0,0,0,0.06);
  --sh-lg: 0 8px 30px rgba(0,0,0,0.08);
  --sh-glow: 0 0 0 3px rgba(79,70,229,0.08);
  --font: 'Inter', -apple-system, sans-serif;
  --mono: 'JetBrains Mono', 'Consolas', monospace;
}}
html{{scroll-behavior:smooth}}
body{{font-family:var(--font);background:var(--bg);color:var(--text-p);line-height:1.6;-webkit-font-smoothing:antialiased;overflow-x:hidden}}

/* Scrollbar */
::-webkit-scrollbar{{width:6px;height:6px}}
::-webkit-scrollbar-track{{background:transparent}}
::-webkit-scrollbar-thumb{{background:linear-gradient(180deg,var(--neon),var(--purple));border-radius:3px}}

/* Layout */
.sidebar{{position:fixed;top:0;left:0;width:56px;height:100vh;background:var(--bg-card);border-right:1.5px solid var(--border);display:flex;flex-direction:column;align-items:center;padding:16px 0;gap:4px;z-index:100;box-shadow:var(--sh-sm)}}
.sidebar .nav-logo{{width:36px;height:36px;border-radius:var(--r-sm);background:linear-gradient(135deg,#d97706,#f59e0b);display:flex;align-items:center;justify-content:center;color:#fff;font-weight:900;font-size:0.6em;letter-spacing:-0.5px;margin-bottom:12px;cursor:pointer}}
.sidebar .nav-item{{width:38px;height:38px;border-radius:var(--r-sm);display:flex;align-items:center;justify-content:center;color:var(--text-m);cursor:pointer;transition:all .2s;font-size:1em;position:relative}}
.sidebar .nav-item:hover{{background:var(--neon-l);color:var(--neon)}}
.sidebar .nav-item.active{{background:var(--neon-l);color:var(--neon)}}
.sidebar .nav-item .tooltip{{position:absolute;left:52px;background:#1e293b;color:#fff;padding:4px 10px;border-radius:6px;font-size:0.72em;font-weight:600;white-space:nowrap;opacity:0;pointer-events:none;transition:opacity .2s}}
.sidebar .nav-item:hover .tooltip{{opacity:1}}
.sidebar .nav-spacer{{flex:1}}

.main-content{{margin-left:56px;padding:24px 32px 60px;max-width:1440px}}

/* Reveal animation */
.reveal{{opacity:0;transform:translateY(24px);transition:opacity .6s cubic-bezier(.16,1,.3,1), transform .6s cubic-bezier(.16,1,.3,1)}}
.reveal.vis{{opacity:1;transform:translateY(0)}}

/* Top Bar */
.top-bar{{display:flex;align-items:center;justify-content:space-between;margin-bottom:28px;flex-wrap:wrap;gap:12px;padding:12px 0}}
.brand{{display:flex;align-items:center;gap:14px}}
.brand-logo{{width:44px;height:44px;clip-path:polygon(50% 0%,100% 25%,100% 75%,50% 100%,0% 75%,0% 25%);background:linear-gradient(135deg,#d97706,#f59e0b);display:flex;align-items:center;justify-content:center;color:#fff;font-weight:900;font-size:0.7em;letter-spacing:0.5px}}
.brand-text h1{{font-size:1.25em;font-weight:800;color:var(--text-h);letter-spacing:-0.3px;line-height:1.2}}
.brand-text span{{font-size:0.72em;color:var(--text-m);font-weight:500}}
.top-meta{{display:flex;align-items:center;gap:10px;flex-wrap:wrap}}
.top-badge{{display:inline-flex;align-items:center;gap:5px;padding:5px 14px;border-radius:20px;font-size:0.75em;font-weight:600;border:1px solid}}
.top-badge.date{{background:var(--neon-l);color:var(--neon);border-color:rgba(79,70,229,0.15)}}
.top-badge.type-first{{background:var(--purple-l);color:var(--purple);border-color:rgba(124,58,237,0.15)}}
.top-badge.agent{{background:var(--cyan-l);color:var(--cyan);border-color:rgba(8,145,178,0.15)}}

/* Search */
.search-wrap{{position:relative;margin-bottom:24px}}
.search-input{{width:100%;padding:12px 20px 12px 44px;background:#fff;border:1.5px solid var(--border);border-radius:var(--r-md);font-size:0.88em;color:var(--text-h);font-family:var(--font);outline:none;transition:border-color .2s, box-shadow .2s}}
.search-input:focus{{border-color:var(--neon);box-shadow:var(--sh-glow)}}
.search-input::placeholder{{color:var(--text-m)}}
.search-icon{{position:absolute;left:16px;top:50%;transform:translateY(-50%);color:var(--text-m)}}
.search-count{{position:absolute;right:14px;top:50%;transform:translateY(-50%);font-size:0.72em;color:var(--text-m);font-family:var(--mono)}}

/* Severity Filter Buttons */
.filter-bar{{display:flex;gap:8px;margin-bottom:20px;flex-wrap:wrap;align-items:center}}
.filter-bar .filter-label{{font-size:0.78em;font-weight:600;color:var(--text-s);margin-right:4px}}
.filter-btn{{padding:6px 16px;border-radius:20px;font-size:0.78em;font-weight:600;border:1.5px solid var(--border);background:#fff;cursor:pointer;transition:all .2s;display:inline-flex;align-items:center;gap:5px}}
.filter-btn:hover{{border-color:var(--border-hover);box-shadow:var(--sh-sm)}}
.filter-btn.active{{color:#fff}}
.filter-btn.all.active{{background:var(--grad);border-color:var(--neon)}}
.filter-btn.critical.active{{background:var(--red);border-color:var(--red)}}
.filter-btn.major.active{{background:var(--orange);border-color:var(--orange)}}
.filter-btn.medium.active{{background:var(--cyan);border-color:var(--cyan)}}
.filter-btn.minor.active{{background:var(--slate);border-color:var(--slate)}}
.filter-count{{font-family:var(--mono);font-size:0.9em}}

/* KPI Cards */
.kpi-grid{{display:grid;grid-template-columns:repeat(6,1fr);gap:14px;margin-bottom:20px}}
@media(max-width:1200px){{.kpi-grid{{grid-template-columns:repeat(3,1fr)}}}}
@media(max-width:700px){{.kpi-grid{{grid-template-columns:repeat(2,1fr)}}}}
.kpi{{background:#fff;border:1.5px solid var(--border);border-radius:var(--r-md);padding:18px 16px;position:relative;overflow:hidden;transition:all .25s}}
.kpi::before{{content:'';position:absolute;top:0;left:0;right:0;height:3px}}
.kpi:hover{{border-color:var(--border-hover);box-shadow:var(--sh-md);transform:translateY(-2px)}}
.kpi-label{{font-size:0.72em;font-weight:600;color:var(--text-s);text-transform:uppercase;letter-spacing:0.5px;margin-bottom:8px}}
.kpi-val{{font-size:2.2em;font-weight:800;line-height:1;color:var(--text-h);font-family:var(--mono)}}
.kpi-sub{{font-size:0.7em;color:var(--text-m);margin-top:6px;display:flex;gap:6px;flex-wrap:wrap}}
.kpi-dot{{width:8px;height:8px;border-radius:50%;display:inline-block}}
.kpi.total::before{{background:var(--grad)}}
.kpi.critical::before{{background:var(--red)}}
.kpi.critical .kpi-val{{color:var(--red)}}
.kpi.major::before{{background:var(--orange)}}
.kpi.major .kpi-val{{color:var(--orange)}}
.kpi.medium::before{{background:var(--cyan)}}
.kpi.medium .kpi-val{{color:var(--cyan)}}
.kpi.minor::before{{background:var(--slate)}}
.kpi.minor .kpi-val{{color:var(--slate)}}
.kpi.rec::before{{background:var(--red)}}
.rec-badge{{display:inline-block;padding:6px 16px;border-radius:20px;font-size:0.82em;font-weight:700;letter-spacing:0.5px;margin-top:4px}}
.rec-badge.rework{{background:var(--red-l);color:var(--red);border:1px solid rgba(220,38,38,0.2)}}
.rec-badge.approve{{background:var(--green-l);color:var(--green);border:1px solid rgba(5,150,105,0.2)}}
.rec-badge.approve-changes{{background:var(--orange-l);color:var(--orange);border:1px solid rgba(234,88,12,0.2)}}

.exec-summary{{background:#fff;border:1.5px solid var(--border);border-radius:var(--r-lg);padding:20px 24px;margin-bottom:24px;font-size:0.88em;line-height:1.7;color:var(--text-p);box-shadow:var(--sh-sm)}}
.exec-summary strong{{color:var(--text-h)}}

/* Section Cards */
.sec{{background:#fff;border:1.5px solid var(--border);border-radius:var(--r-lg);margin-bottom:16px;overflow:hidden;box-shadow:var(--sh-sm);transition:box-shadow .2s}}
.sec:hover{{box-shadow:var(--sh-md)}}
.sec-head{{padding:16px 20px;display:flex;align-items:center;gap:12px;cursor:pointer;user-select:none;transition:background .15s}}
.sec-head:hover{{background:var(--bg-subtle)}}
.sec-ico{{width:36px;height:36px;border-radius:var(--r-sm);display:flex;align-items:center;justify-content:center;font-size:1em;flex-shrink:0}}
.sec-title{{font-size:0.95em;font-weight:700;color:var(--text-h);flex:1}}
.sec-badge{{font-size:0.72em;font-weight:600;padding:3px 10px;border-radius:12px}}
.sec-chev{{color:var(--text-m);font-size:0.85em;transition:transform .25s}}
.sec-chev.shut{{transform:rotate(-90deg)}}
.sec-body{{padding:0 20px 20px}}
.sec-body.shut{{display:none}}

/* File Chips */
.file-group{{margin-bottom:14px}}
.file-group-label{{font-size:0.78em;font-weight:700;color:var(--text-s);margin-bottom:8px;text-transform:uppercase;letter-spacing:0.5px}}
.file-chips{{display:flex;flex-wrap:wrap;gap:6px}}
.file-chip{{display:inline-flex;align-items:center;gap:4px;padding:5px 12px;border-radius:20px;font-size:0.75em;font-family:var(--mono);font-weight:500;background:var(--bg-subtle);border:1px solid var(--border);color:var(--text-p);transition:all .2s}}
.file-chip:hover{{border-color:var(--neon);background:var(--neon-l)}}

/* Tabs */
.tabs{{display:flex;gap:2px;padding:3px;background:var(--bg-subtle);border:1.5px solid var(--border);border-radius:var(--r-md);margin-bottom:20px}}
.tab{{flex:1;padding:10px 16px;text-align:center;cursor:pointer;font-size:.82em;font-weight:600;color:var(--text-s);border-radius:var(--r-sm);transition:all .2s;user-select:none;display:flex;align-items:center;justify-content:center;gap:6px}}
.tab:hover{{color:var(--text-h);background:rgba(255,255,255,.7)}}
.tab.on{{color:#fff;box-shadow:0 2px 8px rgba(0,0,0,0.1)}}
.tab.critical.on{{background:var(--red)}}
.tab.major.on{{background:var(--orange)}}
.tab.medium.on{{background:var(--cyan)}}
.tab.minor.on{{background:var(--slate)}}
.tab-count{{font-family:var(--mono);font-weight:700}}
.tab-pane{{display:none;animation:fadeUp .4s ease-out}}
.tab-pane.vis{{display:block}}
@keyframes fadeUp{{from{{opacity:0;transform:translateY(10px)}}to{{opacity:1;transform:translateY(0)}}}}

/* Issue Cards */
.issue-card{{background:#fff;border:1.5px solid var(--border);border-radius:var(--r-md);margin-bottom:10px;overflow:hidden;transition:all .2s}}
.issue-card:hover{{box-shadow:var(--sh-md)}}
.issue-card.critical{{border-left:4px solid var(--red)}}
.issue-card.major{{border-left:4px solid var(--orange)}}
.issue-card.medium{{border-left:4px solid var(--cyan)}}
.issue-card.minor{{border-left:4px solid var(--slate)}}
.issue-header{{padding:12px 16px;display:flex;align-items:center;gap:10px;cursor:pointer;user-select:none;flex-wrap:wrap}}
.issue-header:hover{{background:var(--bg-subtle)}}
.issue-num{{font-family:var(--mono);font-size:0.78em;font-weight:700;color:var(--text-m);min-width:28px}}
.issue-cat{{padding:3px 10px;border-radius:12px;font-size:0.7em;font-weight:700;white-space:nowrap}}
.issue-cat.critical{{background:var(--red-l);color:var(--red)}}
.issue-cat.major{{background:var(--orange-l);color:var(--orange)}}
.issue-cat.medium{{background:var(--cyan-l);color:var(--cyan)}}
.issue-cat.minor{{background:var(--slate-l);color:var(--slate)}}
.issue-file{{font-family:var(--mono);font-size:0.75em;color:var(--neon);white-space:nowrap}}
.issue-desc{{font-size:0.85em;font-weight:600;color:var(--text-h);flex:1;min-width:200px}}
.issue-toggle{{color:var(--text-m);font-size:0.85em;transition:transform .25s;flex-shrink:0}}
.issue-toggle.open{{transform:rotate(180deg)}}
.issue-body{{display:none;padding:0 16px 16px;border-top:1px solid var(--border);animation:fadeUp .3s ease-out}}
.issue-body.open{{display:block}}
.issue-section{{margin-top:14px}}
.issue-section-label{{font-size:0.72em;font-weight:700;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:6px;display:flex;align-items:center;gap:6px}}
.issue-section-label.current{{color:var(--text-s)}}
.issue-section-label.required{{color:var(--green)}}
.issue-section-label.reference{{color:var(--purple)}}
.issue-current{{background:#f8f9fc;border:1px solid var(--border);border-radius:var(--r-sm);padding:12px 14px;font-size:0.84em;line-height:1.6;color:var(--text-p)}}
.issue-required{{background:rgba(5,150,105,0.04);border:1px solid rgba(5,150,105,0.15);border-radius:var(--r-sm);padding:12px 14px;font-size:0.84em;line-height:1.6;color:var(--text-p)}}
.ref-tag{{display:inline-block;padding:3px 10px;border-radius:12px;font-size:0.72em;font-weight:600;background:var(--purple-l);color:var(--purple);border:1px solid rgba(124,58,237,0.15);margin-right:4px;margin-bottom:4px}}

/* Code Blocks */
.code-wrap{{position:relative;margin-top:6px}}
.code-block{{background:#1e293b;color:#e2e8f0;border-radius:var(--r-sm);padding:14px 16px;font-family:var(--mono);font-size:0.8em;line-height:1.6;overflow-x:auto;white-space:pre;tab-size:2}}
.code-block.light{{background:#f8f9fc;color:#1e293b;border:1px solid var(--border)}}
.code-block .str{{color:#a5d6ff}}
.code-block .key{{color:#7dd3fc}}
.code-block .num{{color:#fbbf24}}
.code-block .bool{{color:#f472b6}}
.code-block .null{{color:#94a3b8}}
.code-label{{position:absolute;top:8px;left:12px;font-size:0.65em;font-weight:700;text-transform:uppercase;letter-spacing:0.8px;color:#64748b;background:rgba(30,41,59,0.5);padding:2px 8px;border-radius:4px}}
.code-label.fix{{color:#34d399;background:rgba(5,150,105,0.15)}}
.copy-btn{{position:absolute;top:8px;right:8px;padding:4px 10px;border-radius:6px;font-size:0.68em;font-weight:600;background:rgba(255,255,255,0.1);color:#94a3b8;border:1px solid rgba(255,255,255,0.1);cursor:pointer;transition:all .2s;font-family:var(--font)}}
.copy-btn:hover{{background:rgba(255,255,255,0.2);color:#fff}}
.copy-btn.copied{{background:rgba(5,150,105,0.2);color:#34d399}}

/* Tables */
table{{width:100%;border-collapse:collapse;font-size:.84em}}
th{{background:#f0f2f8;color:var(--text-s);padding:10px 14px;text-align:left;font-size:.72em;font-weight:700;text-transform:uppercase;letter-spacing:.8px;border-bottom:1px solid var(--border);cursor:pointer;user-select:none;transition:background .15s}}
th:hover{{background:#e5e8f0}}
th .sort-arrow{{margin-left:4px;font-size:0.85em;color:var(--text-m)}}
td{{padding:10px 14px;border-bottom:1px solid #e2e6ef;color:var(--text-p)}}
tr:hover td{{background:#f4f5f9}}
.cell-critical{{background:var(--red-l);color:var(--red);font-weight:700;text-align:center}}
.cell-major{{background:var(--orange-l);color:var(--orange);font-weight:700;text-align:center}}
.cell-medium{{background:var(--cyan-l);color:var(--cyan);font-weight:700;text-align:center}}
.cell-minor{{background:var(--slate-l);color:var(--slate);font-weight:700;text-align:center}}
.cell-zero{{color:var(--green);font-weight:600;text-align:center}}
.cell-file{{font-family:var(--mono);font-size:0.88em;font-weight:500;color:var(--neon)}}
tr.total-row td{{font-weight:800;background:var(--bg-subtle);border-top:2px solid var(--border)}}
tr.highlight-row{{background:rgba(220,38,38,0.03)}}

/* What Passed */
.pass-card{{background:#fff;border:1.5px solid rgba(5,150,105,0.2);border-left:4px solid var(--green);border-radius:var(--r-md);padding:14px 18px;margin-bottom:10px;transition:all .2s}}
.pass-card:hover{{box-shadow:var(--sh-md);transform:translateY(-1px)}}
.pass-icon{{color:var(--green);margin-right:8px;font-weight:700}}
.pass-text{{font-size:0.85em;line-height:1.6}}
.pass-text strong{{color:var(--text-h)}}
.pass-file{{font-family:var(--mono);font-weight:600;color:var(--neon);font-size:0.92em}}

/* Checklist */
.check-badge{{display:inline-flex;align-items:center;gap:4px;padding:4px 14px;border-radius:20px;font-size:0.75em;font-weight:700;letter-spacing:0.3px}}
.check-badge.pass{{background:var(--green-l);color:var(--green);border:1px solid rgba(5,150,105,0.2)}}
.check-badge.fail{{background:var(--red-l);color:var(--red);border:1px solid rgba(220,38,38,0.2)}}
.check-notes{{font-size:0.82em;line-height:1.5;color:var(--text-p);max-width:600px}}

/* Priority Remediation */
.prio-card{{display:flex;align-items:flex-start;gap:14px;padding:14px 18px;margin-bottom:10px;background:#fff;border:1.5px solid var(--border);border-radius:var(--r-md);transition:all .2s}}
.prio-card:hover{{box-shadow:var(--sh-md);transform:translateY(-1px)}}
.prio-card.critical{{border-left:4px solid var(--red)}}
.prio-card.major{{border-left:4px solid var(--orange)}}
.prio-card.medium{{border-left:4px solid var(--cyan)}}
.prio-card.minor{{border-left:4px solid var(--slate)}}
.prio-num{{width:32px;height:32px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:0.82em;font-weight:800;color:#fff;flex-shrink:0;font-family:var(--mono)}}
.prio-card.critical .prio-num{{background:var(--red)}}
.prio-card.major .prio-num{{background:var(--orange)}}
.prio-card.medium .prio-num{{background:var(--cyan)}}
.prio-card.minor .prio-num{{background:var(--slate)}}
.prio-sev{{padding:3px 10px;border-radius:12px;font-size:0.7em;font-weight:700;white-space:nowrap;margin-bottom:4px;display:inline-block}}
.prio-desc{{font-size:0.85em;line-height:1.6;color:var(--text-p)}}
.prio-desc strong{{color:var(--text-h)}}

/* Summary Final */
.summary-card{{background:linear-gradient(135deg,rgba(79,70,229,0.04),rgba(124,58,237,0.04));border:1.5px solid rgba(79,70,229,0.15);border-radius:var(--r-lg);padding:28px;margin-bottom:24px}}
.summary-card h2{{font-size:1.1em;font-weight:800;color:var(--text-h);margin-bottom:12px}}
.summary-stats{{display:flex;gap:12px;margin-bottom:16px;flex-wrap:wrap}}
.summary-stat{{padding:6px 14px;border-radius:20px;font-size:0.82em;font-weight:700}}
.summary-text{{font-size:0.9em;line-height:1.7;color:var(--text-p)}}

/* Footer */
.footer{{text-align:center;padding:24px 0;border-top:1px solid var(--border);margin-top:32px}}
.footer-text{{font-size:0.78em;color:var(--text-m)}}
.footer-text strong{{color:var(--text-s)}}

/* Back to top */
.back-top{{position:fixed;bottom:24px;right:24px;width:42px;height:42px;border-radius:50%;background:var(--grad);color:#fff;display:flex;align-items:center;justify-content:center;font-size:1.1em;cursor:pointer;box-shadow:var(--sh-lg);opacity:0;transform:translateY(20px);transition:all .3s;z-index:99;border:none}}
.back-top.show{{opacity:1;transform:translateY(0)}}
.back-top:hover{{transform:translateY(-2px);box-shadow:0 12px 36px rgba(79,70,229,0.3)}}

/* Dark code toggle */
.code-toggle{{display:inline-flex;align-items:center;gap:6px;padding:4px 12px;border-radius:16px;font-size:0.72em;font-weight:600;background:var(--bg-subtle);border:1px solid var(--border);cursor:pointer;color:var(--text-s);margin-bottom:12px;transition:all .2s}}
.code-toggle:hover{{border-color:var(--neon);color:var(--neon)}}

/* Print */
@media print{{
  .sidebar,.back-top,.search-wrap,.filter-bar,.code-toggle,.copy-btn{{display:none!important}}
  .main-content{{margin-left:0!important;padding:10px!important}}
  .sec,.kpi,.issue-card,.pass-card,.prio-card,.exec-summary,.summary-card{{break-inside:avoid;box-shadow:none!important;border-color:#ccc!important}}
  .issue-body{{display:block!important}}
  .sec-body{{display:block!important}}
  body{{background:#fff}}
  .code-block{{background:#f0f2f8!important;color:#1e293b!important;border:1px solid #ccc}}
}}
</style>
</head>
<body>

<!-- Sidebar Navigation -->
<nav class="sidebar">
  <div class="nav-logo" onclick="window.scrollTo({{top:0,behavior:'smooth'}})">ATCO</div>
  <div class="nav-item active" onclick="scrollToSection('exec-section')">
    <svg width="18" height="18" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="12" height="12" rx="2"/><line x1="7" y1="7" x2="11" y2="7"/><line x1="7" y1="11" x2="11" y2="11"/></svg>
    <span class="tooltip">Executive Summary</span>
  </div>
  <div class="nav-item" onclick="scrollToSection('files-section')">
    <svg width="18" height="18" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 3h5l2 2h5a1 1 0 011 1v8a1 1 0 01-1 1H3a1 1 0 01-1-1V4a1 1 0 011-1z"/></svg>
    <span class="tooltip">Files Reviewed</span>
  </div>
  {followup_nav}
  <div class="nav-item" onclick="scrollToSection('issues-section')">
    <svg width="18" height="18" fill="none" stroke="currentColor" stroke-width="2"><circle cx="9" cy="9" r="6"/><line x1="9" y1="6" x2="9" y2="9"/><circle cx="9" cy="12" r="0.5" fill="currentColor"/></svg>
    <span class="tooltip">Issues</span>
  </div>
  <div class="nav-item" onclick="scrollToSection('breakdown-section')">
    <svg width="18" height="18" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="12" height="12" rx="1"/><line x1="3" y1="7" x2="15" y2="7"/><line x1="3" y1="11" x2="15" y2="11"/><line x1="8" y1="7" x2="8" y2="15"/></svg>
    <span class="tooltip">Per-File Breakdown</span>
  </div>
  <div class="nav-item" onclick="scrollToSection('passed-section')">
    <svg width="18" height="18" fill="none" stroke="currentColor" stroke-width="2"><polyline points="4,9 7,12 14,5"/></svg>
    <span class="tooltip">What Passed</span>
  </div>
  <div class="nav-item" onclick="scrollToSection('checklist-section')">
    <svg width="18" height="18" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="4" height="4" rx="1"/><line x1="10" y1="5" x2="15" y2="5"/><rect x="3" y="11" width="4" height="4" rx="1"/><line x1="10" y1="13" x2="15" y2="13"/></svg>
    <span class="tooltip">Checklist</span>
  </div>
  <div class="nav-item" onclick="scrollToSection('prio-section')">
    <svg width="18" height="18" fill="none" stroke="currentColor" stroke-width="2"><line x1="4" y1="5" x2="14" y2="5"/><line x1="4" y1="9" x2="12" y2="9"/><line x1="4" y1="13" x2="10" y2="13"/></svg>
    <span class="tooltip">Remediation Priority</span>
  </div>
  <div class="nav-spacer"></div>
  <div class="nav-item" onclick="window.print()">
    <svg width="18" height="18" fill="none" stroke="currentColor" stroke-width="2"><polyline points="4,7 4,2 14,2 14,7"/><rect x="2" y="7" width="14" height="7" rx="1"/><rect x="5" y="11" width="8" height="4" rx="0.5"/></svg>
    <span class="tooltip">Print</span>
  </div>
</nav>

<div class="main-content">

<!-- Top Bar -->
<header class="top-bar reveal">
  <div class="brand">
    <div class="brand-logo">ATCO</div>
    <div class="brand-text">
      <h1>EDL Code Review Report</h1>
      <span>Azure Data Factory Pipeline Analysis</span>
    </div>
  </div>
  <div class="top-meta">
    <span class="top-badge date">{_esc(review_date)}</span>
    <span class="top-badge {type_class}">{_esc(review_type)}</span>
    {agent_badges}
    {prev_badge}
  </div>
</header>

<!-- Search -->
<div class="search-wrap reveal">
  <svg class="search-icon" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2"><circle cx="8" cy="8" r="5"/><line x1="12" y1="12" x2="16" y2="16"/></svg>
  <input class="search-input" type="text" placeholder="Search issues by keyword, file name, or category..." id="searchInput" oninput="filterIssues()">
  <span class="search-count" id="searchCount"></span>
</div>

<!-- Filter Buttons -->
<div class="filter-bar reveal">
  <span class="filter-label">Filter by severity:</span>
  <button class="filter-btn all active" onclick="setFilter('all')">All <span class="filter-count">{total}</span></button>
  <button class="filter-btn critical" onclick="setFilter('critical')">Critical <span class="filter-count">{critical}</span></button>
  <button class="filter-btn major" onclick="setFilter('major')">Major <span class="filter-count">{major}</span></button>
  <button class="filter-btn medium" onclick="setFilter('medium')">Medium <span class="filter-count">{medium}</span></button>
  <button class="filter-btn minor" onclick="setFilter('minor')">Minor <span class="filter-count">{minor}</span></button>
</div>

<!-- Executive Summary Section -->
<section id="exec-section">

<!-- KPI Cards -->
<div class="kpi-grid reveal">
  <div class="kpi total">
    <div class="kpi-label">Total Issues</div>
    <div class="kpi-val" data-count="{total}">0</div>
    <div class="kpi-sub">
      <span><span class="kpi-dot" style="background:var(--red)"></span> {critical}</span>
      <span><span class="kpi-dot" style="background:var(--orange)"></span> {major}</span>
      <span><span class="kpi-dot" style="background:var(--cyan)"></span> {medium}</span>
      <span><span class="kpi-dot" style="background:var(--slate)"></span> {minor}</span>
    </div>
  </div>
  <div class="kpi critical">
    <div class="kpi-label">Critical</div>
    <div class="kpi-val" data-count="{critical}">0</div>
    <div class="kpi-sub">Must fix before merge</div>
  </div>
  <div class="kpi major">
    <div class="kpi-label">Major</div>
    <div class="kpi-val" data-count="{major}">0</div>
    <div class="kpi-sub">Should fix</div>
  </div>
  <div class="kpi medium">
    <div class="kpi-label">Medium</div>
    <div class="kpi-val" data-count="{medium}">0</div>
    <div class="kpi-sub">Recommended</div>
  </div>
  <div class="kpi minor">
    <div class="kpi-label">Minor</div>
    <div class="kpi-val" data-count="{minor}">0</div>
    <div class="kpi-sub">Suggestions</div>
  </div>
  <div class="kpi rec">
    <div class="kpi-label">Recommendation</div>
    <div class="rec-badge {rec_class}">{_esc(recommendation.upper())}</div>
  </div>
</div>

<!-- Executive Summary Text -->
<div class="exec-summary reveal">
  {_md_inline_to_html(data['exec_summary']['paragraph'])}
</div>
</section>

<!-- Files Reviewed Section -->
<section id="files-section">
<div class="sec reveal">
  <div class="sec-head" onclick="toggleSection(this)">
    <div class="sec-ico" style="background:var(--neon-l);color:var(--neon)">
      <svg width="18" height="18" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 3h5l2 2h5a1 1 0 011 1v8a1 1 0 01-1 1H3a1 1 0 01-1-1V4a1 1 0 011-1z"/></svg>
    </div>
    <div class="sec-title">Files Reviewed <span class="sec-badge" style="background:var(--neon-l);color:var(--neon)">{file_count} files</span></div>
    <span class="sec-chev shut">&#9660;</span>
  </div>
  <div class="sec-body shut">
    {file_chips_html}
  </div>
</div>
</section>

{followup_sections}

<!-- Issues Section with Tabs -->
<section id="issues-section">
<div class="sec reveal">
  <div class="sec-head" onclick="toggleSection(this)">
    <div class="sec-ico" style="background:var(--red-l);color:var(--red)">
      <svg width="18" height="18" fill="none" stroke="currentColor" stroke-width="2"><circle cx="9" cy="9" r="6"/><line x1="9" y1="6" x2="9" y2="9"/><circle cx="9" cy="12" r="0.5" fill="currentColor"/></svg>
    </div>
    <div class="sec-title">Issues <span class="sec-badge" style="background:var(--red-l);color:var(--red)">{total} total</span></div>
    <span class="sec-chev">&#9660;</span>
  </div>
  <div class="sec-body">

    <div style="display:flex;justify-content:flex-end;margin-bottom:8px">
      <button class="code-toggle" onclick="toggleCodeTheme()">
        <svg width="14" height="14" fill="none" stroke="currentColor" stroke-width="2"><circle cx="7" cy="7" r="4"/><line x1="7" y1="1" x2="7" y2="3"/><line x1="7" y1="11" x2="7" y2="13"/><line x1="1" y1="7" x2="3" y2="7"/><line x1="11" y1="7" x2="13" y2="7"/></svg>
        Toggle code theme
      </button>
    </div>

    <div class="tabs">
      <div class="tab critical {tab_classes['critical']}" onclick="switchTab('critical')">Critical <span class="tab-count">{critical}</span></div>
      <div class="tab major {tab_classes['major']}" onclick="switchTab('major')">Major <span class="tab-count">{major}</span></div>
      <div class="tab medium {tab_classes['medium']}" onclick="switchTab('medium')">Medium <span class="tab-count">{medium}</span></div>
      <div class="tab minor {tab_classes['minor']}" onclick="switchTab('minor')">Minor <span class="tab-count">{minor}</span></div>
    </div>

    <!-- CRITICAL TAB -->
    <div class="tab-pane {pane_classes['critical']}" id="tab-critical">
      {critical_cards}
    </div>

    <!-- MAJOR TAB -->
    <div class="tab-pane {pane_classes['major']}" id="tab-major">
      {major_cards}
    </div>

    <!-- MEDIUM TAB -->
    <div class="tab-pane {pane_classes['medium']}" id="tab-medium">
      {medium_cards}
    </div>

    <!-- MINOR TAB -->
    <div class="tab-pane {pane_classes['minor']}" id="tab-minor">
      {minor_cards}
    </div>

  </div>
</div>
</section>

<!-- Per-File Breakdown Section -->
<section id="breakdown-section">
<div class="sec reveal">
  <div class="sec-head" onclick="toggleSection(this)">
    <div class="sec-ico" style="background:var(--purple-l);color:var(--purple)">
      <svg width="18" height="18" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="12" height="12" rx="1"/><line x1="3" y1="7" x2="15" y2="7"/><line x1="3" y1="11" x2="15" y2="11"/><line x1="8" y1="7" x2="8" y2="15"/></svg>
    </div>
    <div class="sec-title">Per-File Breakdown</div>
    <span class="sec-chev">&#9660;</span>
  </div>
  <div class="sec-body">
    <div style="overflow-x:auto">
    <table id="breakdownTable">
      <thead>
        <tr>
          <th onclick="sortTable(0)">File <span class="sort-arrow">&#9650;</span></th>
          <th onclick="sortTable(1)">Critical <span class="sort-arrow"></span></th>
          <th onclick="sortTable(2)">Major <span class="sort-arrow"></span></th>
          <th onclick="sortTable(3)">Medium <span class="sort-arrow"></span></th>
          <th onclick="sortTable(4)">Minor <span class="sort-arrow"></span></th>
          <th onclick="sortTable(5)">Total <span class="sort-arrow"></span></th>
        </tr>
      </thead>
      <tbody>
        {breakdown_rows}
      </tbody>
    </table>
    </div>
  </div>
</div>
</section>

<!-- What Passed Section -->
<section id="passed-section">
<div class="sec reveal">
  <div class="sec-head" onclick="toggleSection(this)">
    <div class="sec-ico" style="background:var(--green-l);color:var(--green)">
      <svg width="18" height="18" fill="none" stroke="currentColor" stroke-width="2"><polyline points="4,9 7,12 14,5"/></svg>
    </div>
    <div class="sec-title">What Passed <span class="sec-badge" style="background:var(--green-l);color:var(--green)">{len(data['what_passed'])} items</span></div>
    <span class="sec-chev">&#9660;</span>
  </div>
  <div class="sec-body">
    {passed_html}
  </div>
</div>
</section>

<!-- Review Checklist Status -->
<section id="checklist-section">
<div class="sec reveal">
  <div class="sec-head" onclick="toggleSection(this)">
    <div class="sec-ico" style="background:var(--gold-l);color:var(--gold)">
      <svg width="18" height="18" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="4" height="4" rx="1"/><line x1="10" y1="5" x2="15" y2="5"/><rect x="3" y="11" width="4" height="4" rx="1"/><line x1="10" y1="13" x2="15" y2="13"/></svg>
    </div>
    <div class="sec-title">Review Checklist Status <span class="sec-badge" style="background:var(--red-l);color:var(--red)">{pass_count} PASS / {fail_count} FAIL</span></div>
    <span class="sec-chev">&#9660;</span>
  </div>
  <div class="sec-body">
    <div style="overflow-x:auto">
    <table>
      <thead>{checklist_header}</thead>
      <tbody>
        {checklist_html}
      </tbody>
    </table>
    </div>
  </div>
</div>
</section>

<!-- Priority Remediation Order -->
<section id="prio-section">
<div class="sec reveal">
  <div class="sec-head" onclick="toggleSection(this)">
    <div class="sec-ico" style="background:var(--orange-l);color:var(--orange)">
      <svg width="18" height="18" fill="none" stroke="currentColor" stroke-width="2"><line x1="4" y1="5" x2="14" y2="5"/><line x1="4" y1="9" x2="12" y2="9"/><line x1="4" y1="13" x2="10" y2="13"/></svg>
    </div>
    <div class="sec-title">Priority Remediation Order <span class="sec-badge" style="background:var(--orange-l);color:var(--orange)">{len(data['priority_remediation'])} actions</span></div>
    <span class="sec-chev">&#9660;</span>
  </div>
  <div class="sec-body">
    {prio_html}
  </div>
</div>
</section>

<!-- Summary Section -->
<div class="summary-card reveal">
  <h2>Final Summary</h2>
  <div class="summary-stats">
    <span class="summary-stat" style="background:var(--red-l);color:var(--red)">{critical} Critical</span>
    <span class="summary-stat" style="background:var(--orange-l);color:var(--orange)">{major} Major</span>
    <span class="summary-stat" style="background:var(--cyan-l);color:var(--cyan)">{medium} Medium</span>
    <span class="summary-stat" style="background:var(--slate-l);color:var(--slate)">{minor} Minor</span>
    <span class="summary-stat" style="background:var(--red-l);color:var(--red);font-weight:800">{_esc(recommendation.upper())}</span>
  </div>
  <p class="summary-text">
    {summary_paragraph}
  </p>
</div>

<!-- Footer -->
<footer class="footer reveal">
  <p class="footer-text">Generated by <strong>ATCO EDL Code Review Utility</strong> | {_esc(review_date)} {now.split(' ')[1] if ' ' in now else ''} UTC</p>
  <p class="footer-text" style="margin-top:4px">Converted from Markdown to HTML at {now} UTC</p>
</footer>

</div><!-- end main-content -->

<!-- Back to Top Button -->
<button class="back-top" id="backTop" onclick="window.scrollTo({{top:0,behavior:'smooth'}})">&#9650;</button>

<script>
// ===== Scroll reveal =====
const observer = new IntersectionObserver((entries) => {{
  entries.forEach(e => {{ if (e.isIntersecting) {{ e.target.classList.add('vis'); observer.unobserve(e.target); }} }});
}}, {{ threshold: 0.08 }});
document.querySelectorAll('.reveal').forEach(el => observer.observe(el));

// ===== Animated counters =====
function animateCounters() {{
  document.querySelectorAll('.kpi-val[data-count]').forEach(el => {{
    const target = parseInt(el.dataset.count);
    const duration = 1200;
    const start = performance.now();
    function update(now) {{
      const elapsed = now - start;
      const progress = Math.min(elapsed / duration, 1);
      const eased = 1 - Math.pow(1 - progress, 3);
      el.textContent = Math.round(target * eased);
      if (progress < 1) requestAnimationFrame(update);
    }}
    requestAnimationFrame(update);
  }});
}}
setTimeout(animateCounters, 300);

// ===== Toggle section =====
function toggleSection(head) {{
  const body = head.nextElementSibling;
  const chev = head.querySelector('.sec-chev');
  body.classList.toggle('shut');
  chev.classList.toggle('shut');
}}

// ===== Toggle issue =====
function toggleIssue(header) {{
  const body = header.nextElementSibling;
  const toggle = header.querySelector('.issue-toggle');
  body.classList.toggle('open');
  toggle.classList.toggle('open');
}}

// ===== Tab switching =====
function switchTab(severity) {{
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('on'));
  document.querySelectorAll('.tab-pane').forEach(p => p.classList.remove('vis'));
  document.querySelector('.tab.' + severity).classList.add('on');
  document.getElementById('tab-' + severity).classList.add('vis');
}}

// ===== Severity filter =====
let currentFilter = 'all';
function setFilter(sev) {{
  currentFilter = sev;
  document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
  document.querySelector('.filter-btn.' + sev).classList.add('active');
  document.querySelectorAll('.issue-card').forEach(card => {{
    if (sev === 'all' || card.dataset.severity === sev) {{
      card.style.display = '';
    }} else {{
      card.style.display = 'none';
    }}
  }});
  // Auto-switch to matching tab
  if (sev !== 'all') {{
    switchTab(sev);
  }}
}}

// ===== Search =====
function filterIssues() {{
  const query = document.getElementById('searchInput').value.toLowerCase().trim();
  const cards = document.querySelectorAll('.issue-card');
  let count = 0;
  cards.forEach(card => {{
    const text = card.dataset.text + ' ' + card.innerText.toLowerCase();
    if (!query || text.includes(query)) {{
      card.style.display = '';
      count++;
    }} else {{
      card.style.display = 'none';
    }}
  }});
  document.getElementById('searchCount').textContent = query ? count + ' found' : '';
}}

// ===== Copy code =====
function copyCode(btn) {{
  const code = btn.parentElement.querySelector('.code-block').textContent;
  navigator.clipboard.writeText(code).then(() => {{
    btn.textContent = 'Copied!';
    btn.classList.add('copied');
    setTimeout(() => {{ btn.textContent = 'Copy'; btn.classList.remove('copied'); }}, 2000);
  }});
}}

// ===== Code theme toggle =====
let darkCode = true;
function toggleCodeTheme() {{
  darkCode = !darkCode;
  document.querySelectorAll('.code-block').forEach(block => {{
    block.classList.toggle('light', !darkCode);
  }});
}}

// ===== Table sorting =====
let sortCol = -1, sortAsc = true;
function sortTable(col) {{
  const table = document.getElementById('breakdownTable');
  if (!table) return;
  const tbody = table.querySelector('tbody');
  const rows = Array.from(tbody.querySelectorAll('tr:not(.total-row)'));
  if (sortCol === col) {{ sortAsc = !sortAsc; }} else {{ sortCol = col; sortAsc = col === 0; }}
  rows.sort((a, b) => {{
    let va = a.cells[col].textContent.trim();
    let vb = b.cells[col].textContent.trim();
    if (col > 0) {{ va = parseInt(va) || 0; vb = parseInt(vb) || 0; return sortAsc ? va - vb : vb - va; }}
    return sortAsc ? va.localeCompare(vb) : vb.localeCompare(va);
  }});
  const totalRow = tbody.querySelector('.total-row');
  rows.forEach(r => tbody.insertBefore(r, totalRow));
}}

// ===== Back to top =====
window.addEventListener('scroll', () => {{
  document.getElementById('backTop').classList.toggle('show', window.scrollY > 400);
}});

// ===== Sidebar active state =====
function scrollToSection(id) {{
  const el = document.getElementById(id);
  if (el) el.scrollIntoView({{ behavior: 'smooth' }});
  document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
  if (event && event.currentTarget) event.currentTarget.classList.add('active');
}}

// ===== Scroll spy for sidebar =====
const sections = ['exec-section','files-section'{followup_section_ids},'issues-section','breakdown-section','passed-section','checklist-section','prio-section'];
const navItems = document.querySelectorAll('.sidebar .nav-item:not(:last-child)');
window.addEventListener('scroll', () => {{
  let current = 0;
  sections.forEach((id, i) => {{
    const el = document.getElementById(id);
    if (el && el.getBoundingClientRect().top < 200) current = i;
  }});
  navItems.forEach((n, i) => n.classList.toggle('active', i === current));
}});
</script>
</body>
</html>'''

    return html


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------

def main():
    if len(sys.argv) < 2:
        print("Usage: python3 generate_html_report.py <input.md> [output.html]")
        sys.exit(1)

    input_path = sys.argv[1]
    output_path = sys.argv[2] if len(sys.argv) > 2 else input_path.replace('.md', '.html')

    if not os.path.exists(input_path):
        print(f"Error: Input file not found: {input_path}")
        sys.exit(1)

    with open(input_path, 'r', encoding='utf-8') as f:
        md_content = f.read()

    data = parse_md_report(md_content)
    html_content = generate_html(data)

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html_content)

    total = data['exec_summary']['total']
    critical = data['exec_summary']['critical']
    major = data['exec_summary']['major']
    medium = data['exec_summary']['medium']
    minor = data['exec_summary']['minor']
    size_kb = len(html_content.encode('utf-8')) / 1024

    print(f"HTML report saved to: {output_path}")
    print(f"  Issues: {total} ({critical} Critical, {major} Major, {medium} Medium, {minor} Minor)")
    print(f"  Files reviewed: {len(data['files_reviewed'])}")
    print(f"  HTML size: {size_kb:.1f} KB")
    print(f"  Review type: {data['review_type']}")


if __name__ == "__main__":
    main()
