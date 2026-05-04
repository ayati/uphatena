#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
uphatena.py - Hatena Blog diary poster from timestamped memo file

Usage:
    python3 uphatena.py                        # post today
    python3 uphatena.py --date 2026-04-11      # post specific date
    python3 uphatena.py --dry-run              # preview without posting
    python3 uphatena.py --config /path/to/cfg  # specify config file
"""
import sys
import re
import datetime
import random
import hashlib
import base64
import argparse
import pathlib
import xml.etree.ElementTree as ET

import requests

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
DEFAULT_CONFIG = pathlib.Path(__file__).parent / 'foruphatena.txt'
REQUEST_TIMEOUT = 30  # seconds

ATOM_NS = 'http://www.w3.org/2005/Atom'
APP_NS  = 'http://www.w3.org/2007/app'

# Register once at module level to avoid repeated global side-effects
ET.register_namespace('',    ATOM_NS)
ET.register_namespace('app', APP_NS)

# Date prefix pattern: accepts both YYYY/MM/DD and YYYY-MM-DD separators
_DATE = r'[1-2]\d{3}[/\-]\d{2}[/\-]\d{2}'
# Optional ISO 8601 timezone suffix: Z | +HH:MM | -HH:MM | +HHMM | -HHMM
_TZ   = r'(?:Z|[+\-]\d{2}:?\d{2})'
# Time portion: HH:MM:SS with optional TZ suffix
_TIME = r'\d{2}:\d{2}:\d{2}' + _TZ + r'?'
# Date/time separator: whitespace (legacy) OR literal T (ISO 8601)
_SEP  = r'(?:\s+|T)'

# Matches a public entry: YYYY/MM/DD or YYYY-MM-DD, then HH:MM:SS[TZ] body
PUBLIC_RE  = re.compile(r'^(' + _DATE + r')' + _SEP + r'(' + _TIME + r')\s*(.*)')
# Matches a private entry: date separator [-+] before HH:MM:SS[TZ]
PRIVATE_RE = re.compile(r'^'  + _DATE       + _SEP + r'[-+]'  + _TIME)
# Matches any line starting with a date (either separator)
DATE_START = re.compile(r'^' + _DATE)


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
def load_config(path):
    config = {}
    try:
        with open(path, encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                if '=' in line:
                    key, _, val = line.partition('=')
                    # Strip surrounding whitespace and optional quotes
                    val = val.strip().strip("'\"")
                    config[key.strip()] = val
    except FileNotFoundError:
        sys.exit(f'Config file not found: {path}')

    for key in ('HATENA_ID', 'BLOG_ID', 'API_KEY', 'DIARY_FILE'):
        if key not in config:
            sys.exit(f'Missing required config key: {key}')
    return config


# ---------------------------------------------------------------------------
# WSSE Authentication
# ---------------------------------------------------------------------------
def make_wsse(username, api_key):
    created = datetime.datetime.now().isoformat() + 'Z'
    b_nonce  = hashlib.sha1(str(random.random()).encode()).digest()
    b_digest = hashlib.sha1(b_nonce + created.encode() + api_key.encode()).digest()
    return (
        'UsernameToken Username="{}", PasswordDigest="{}", Nonce="{}", Created="{}"'
        .format(
            username,
            base64.b64encode(b_digest).decode(),
            base64.b64encode(b_nonce).decode(),
            created,
        )
    )

def auth_headers(username, api_key):
    return {
        'X-WSSE': make_wsse(username, api_key),
        'Content-Type': 'application/atom+xml',
    }


# ---------------------------------------------------------------------------
# Memo parsing
# ---------------------------------------------------------------------------
def parse_memo(filepath, target_date):
    """
    Read memo.txt and return list of (time_str, body) for target_date.

    Rules:
    - A line starting with a date prefix (YYYY/MM/DD or YYYY-MM-DD) begins
      a new entry (the header line). Date and time may be separated by
      whitespace (legacy) or by the literal 'T' (ISO 8601). The T form
      requires the hyphen date; YYYY/MM/DDT... is rejected as malformed.
    - The time may carry an ISO 8601 timezone suffix (Z, +HH:MM, -HHMM, ...).
      The suffix is parsed but discarded — the heading shows HH:MM:SS only.
    - Lines NOT starting with a date prefix are continuation lines that
      belong to the most recent header line seen so far.
    - Header lines matching PRIVATE_RE (time preceded by - or +) are private:
      that entry and all its continuation lines are skipped.
    - Header lines for dates other than target_date are also skipped (with
      their continuations).
    - Qualifying entries are collected in file order (memo.txt is written
      newest-first, so result is descending time order).
    - body is a multi-line string; trailing blank lines are stripped.
    """
    target_str = target_date.strftime('%Y/%m/%d')
    entries = []

    # State for the entry currently being accumulated.
    cur_public  = False   # True only for public entries on target_date
    cur_time    = None    # time string of current entry, or None
    cur_lines   = []      # body lines accumulated so far

    def _finalize():
        if cur_public and cur_time is not None:
            lines = cur_lines[:]
            while lines and not lines[-1].strip():
                lines.pop()
            entries.append((cur_time, '\n'.join(lines)))

    try:
        with open(filepath, encoding='utf-8') as f:
            for line in f:
                line = line.rstrip()
                if not DATE_START.match(line):
                    # Continuation line: append to current entry if it qualifies
                    if cur_public:
                        cur_lines.append(line)
                    continue

                # New header line — finalize previous entry first
                _finalize()
                cur_public = False
                cur_time   = None
                cur_lines  = []

                # ISO 8601 T separator is only valid with hyphen-date.
                # Reject e.g. "2026/04/12T14:30:40" as malformed.
                if line[4] == '/' and line[10:11] == 'T':
                    continue

                if PRIVATE_RE.match(line):
                    continue  # private entry; cur_public stays False

                m = PUBLIC_RE.match(line)
                if not m or m.group(1).replace('-', '/') != target_str:
                    continue  # wrong date or unrecognised format

                cur_public = True
                cur_time   = m.group(2)[:8]   # heading uses HH:MM:SS only; TZ suffix discarded
                first_line = m.group(3).strip()
                if first_line:
                    cur_lines.append(first_line)

        _finalize()  # handle the last entry in the file
    except FileNotFoundError:
        sys.exit(f'Diary file not found: {filepath}')
    return entries


# ---------------------------------------------------------------------------
# Blog post formatting
# ---------------------------------------------------------------------------
def format_body(entries):
    """
    entries: list of (time_str, body) in descending time order (file order).
    Returns Markdown string.
    """
    parts = []
    for time_str, body in entries:
        parts.append(f'#### {time_str}\n{body}')
    return '\n\n'.join(parts)


def build_entry_xml(title, body, username, target_date):
    """Build Atom entry XML using ElementTree (handles escaping automatically).

    <updated> is fixed to the end of target_date in JST.  Pinning this value
    ensures that repeated PUT calls never change the <updated> field away from
    the original post date, which is required for date-range searches in
    find_entry_edit_url to keep working on re-runs days or months later.
    """
    root = ET.Element(f'{{{ATOM_NS}}}entry')

    title_el = ET.SubElement(root, f'{{{ATOM_NS}}}title')
    title_el.text = title

    # Pin updated to the target date (JST end-of-day) so future re-runs can
    # still find this entry via updated-min / updated-max filtering.
    updated_el = ET.SubElement(root, f'{{{ATOM_NS}}}updated')
    updated_el.text = target_date.strftime('%Y-%m-%dT23:59:59+09:00')

    author_el = ET.SubElement(root, f'{{{ATOM_NS}}}author')
    name_el   = ET.SubElement(author_el, f'{{{ATOM_NS}}}name')
    name_el.text = username

    content_el = ET.SubElement(root, f'{{{ATOM_NS}}}content')
    content_el.set('type', 'text/x-markdown')
    content_el.text = body

    control_el = ET.SubElement(root, f'{{{APP_NS}}}control')
    draft_el   = ET.SubElement(control_el, f'{{{APP_NS}}}draft')
    draft_el.text = 'no'

    return (
        b'<?xml version="1.0" encoding="utf-8"?>\n'
        + ET.tostring(root, encoding='unicode').encode('utf-8')
    )


# ---------------------------------------------------------------------------
# Hatena Blog AtomPub API helpers
# ---------------------------------------------------------------------------
def collection_url(hatena_id, blog_id):
    return f'https://blog.hatena.ne.jp/{hatena_id}/{blog_id}/atom/entry'


def find_entry_edit_url(hatena_id, blog_id, api_key, title, target_date):
    """
    Search for an existing entry whose title matches `title`.
    Returns the edit URL string, or None if not found.

    Uses updated-min / updated-max to narrow the API response to entries
    whose <updated> falls within target_date (JST).  Because build_entry_xml
    always pins <updated> to the end of target_date, this lookup works
    correctly for any date regardless of when the script runs — avoiding the
    duplicate-post bug that occurred when searching by page offset alone.
    """
    base_url    = collection_url(hatena_id, blog_id)
    updated_min = target_date.strftime('%Y-%m-%dT00:00:00+09:00')
    updated_max = (target_date + datetime.timedelta(days=1)).strftime('%Y-%m-%dT00:00:00+09:00')

    r = requests.get(
        base_url,
        headers=auth_headers(hatena_id, api_key),
        params={'updated-min': updated_min, 'updated-max': updated_max},
        timeout=REQUEST_TIMEOUT,
    )
    if r.status_code != 200:
        sys.exit(f'Failed to fetch entry list: {r.status_code}\n{r.text}')

    root = ET.fromstring(r.content)
    for entry in root.findall(f'{{{ATOM_NS}}}entry'):
        entry_title = entry.findtext(f'{{{ATOM_NS}}}title', '')
        if entry_title == title:
            for link in entry.findall(f'{{{ATOM_NS}}}link'):
                if link.get('rel') == 'edit':
                    return link.get('href')

    return None


def api_post(hatena_id, blog_id, api_key, xml_data):
    return requests.post(
        collection_url(hatena_id, blog_id),
        data=xml_data,
        headers=auth_headers(hatena_id, api_key),
        timeout=REQUEST_TIMEOUT,
    )


def api_put(edit_url, hatena_id, api_key, xml_data):
    return requests.put(
        edit_url,
        data=xml_data,
        headers=auth_headers(hatena_id, api_key),
        timeout=REQUEST_TIMEOUT,
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description='Post Hatena Blog diary from timestamped memo file'
    )
    parser.add_argument(
        '--date',
        metavar='YYYY-MM-DD',
        help='Target date (default: today)',
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Preview post content without actually posting',
    )
    parser.add_argument(
        '--config',
        default=DEFAULT_CONFIG,
        metavar='FILE',
        help=f'Config file path (default: {DEFAULT_CONFIG})',
    )
    args = parser.parse_args()

    # Resolve target date
    if args.date:
        try:
            target_date = datetime.date.fromisoformat(args.date)
        except ValueError:
            sys.exit(f'Invalid date: {args.date!r}  (expected YYYY-MM-DD)')
    else:
        target_date = datetime.date.today()

    title = target_date.isoformat()   # e.g. "2026-04-12"

    # Load config
    cfg = load_config(args.config)
    hatena_id  = cfg['HATENA_ID']
    blog_id    = cfg['BLOG_ID']
    api_key    = cfg['API_KEY']
    diary_file = cfg['DIARY_FILE']

    # Parse memo
    entries = parse_memo(diary_file, target_date)

    if not entries:
        print(f'[{title}] No public entries found. Nothing to post.')
        return

    body     = format_body(entries)
    xml_data = build_entry_xml(title, body, hatena_id, target_date)

    # Dry-run: show and exit
    if args.dry_run:
        print(f'=== dry-run: {title} ({len(entries)} entries) ===')
        print(f'Title: {title}')
        print('Body:')
        print(body)
        return

    # Check for existing entry with the same title
    print(f'[{title}] Searching for existing entry...')
    edit_url = find_entry_edit_url(hatena_id, blog_id, api_key, title, target_date)

    if edit_url:
        print(f'[{title}] Found existing entry. Updating ({edit_url})')
        r = api_put(edit_url, hatena_id, api_key, xml_data)
        if r.status_code == 200:
            print(f'[{title}] Updated successfully. ({len(entries)} entries)')
        else:
            sys.exit(f'Update failed: {r.status_code}\n{r.text}')
    else:
        print(f'[{title}] No existing entry. Creating new post.')
        r = api_post(hatena_id, blog_id, api_key, xml_data)
        if r.status_code == 201:
            print(f'[{title}] Posted successfully. ({len(entries)} entries)')
        else:
            sys.exit(f'Post failed: {r.status_code}\n{r.text}')


if __name__ == '__main__':
    main()
