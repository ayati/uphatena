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
import xml.etree.ElementTree as ET

import requests

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
DEFAULT_CONFIG = 'foruphatena.txt'

ATOM_NS = 'http://www.w3.org/2005/Atom'
APP_NS  = 'http://www.w3.org/2007/app'

# Matches a public entry: YYYY/MM/DD HH:MM:SS body
PUBLIC_RE  = re.compile(r'^([1-2]\d{3}/\d{2}/\d{2})\s+(\d{2}:\d{2}:\d{2})\s*(.*)')
# Matches a private entry: YYYY/MM/DD -HH:MM:SS or +HH:MM:SS
PRIVATE_RE = re.compile(r'^[1-2]\d{3}/\d{2}/\d{2}[ ]+[-+]\d{2}:\d{2}:\d{2}')
# Matches any line starting with YYYY/MM/DD
DATE_START = re.compile(r'^[1-2]\d{3}/\d{2}/\d{2}')


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
    - Lines not starting with YYYY/MM/DD are ignored (including blank lines).
    - Lines matching PRIVATE_RE (time preceded by - or +) are skipped.
    - Remaining PUBLIC_RE matches for target_date are collected in file order
      (memo.txt is written newest-first, so result is descending time order).
    """
    target_str = target_date.strftime('%Y/%m/%d')
    entries = []
    try:
        with open(filepath, encoding='utf-8') as f:
            for line in f:
                line = line.rstrip()
                if not DATE_START.match(line):
                    continue
                if PRIVATE_RE.match(line):
                    continue
                m = PUBLIC_RE.match(line)
                if not m:
                    continue
                if m.group(1) == target_str:
                    entries.append((m.group(2), m.group(3).strip()))
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


def build_entry_xml(title, body, username):
    """Build Atom entry XML using ElementTree (handles escaping automatically)."""
    ET.register_namespace('',    ATOM_NS)
    ET.register_namespace('app', APP_NS)

    root = ET.Element(f'{{{ATOM_NS}}}entry')

    title_el = ET.SubElement(root, f'{{{ATOM_NS}}}title')
    title_el.text = title

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


def find_entry_edit_url(hatena_id, blog_id, api_key, title, max_pages=5):
    """
    Search recent entries for one whose title matches `title`.
    Returns the edit URL string, or None if not found.
    """
    url = collection_url(hatena_id, blog_id)
    page = 1
    while url and page <= max_pages:
        r = requests.get(
            url,
            headers=auth_headers(hatena_id, api_key),
        )
        if r.status_code != 200:
            sys.exit(f'Failed to fetch entry list (page {page}): {r.status_code}\n{r.text}')

        root = ET.fromstring(r.content)

        for entry in root.findall(f'{{{ATOM_NS}}}entry'):
            entry_title = entry.findtext(f'{{{ATOM_NS}}}title', '')
            if entry_title == title:
                for link in entry.findall(f'{{{ATOM_NS}}}link'):
                    if link.get('rel') == 'edit':
                        return link.get('href')

        # Follow 'next' link for pagination
        url = None
        for link in root.findall(f'{{{ATOM_NS}}}link'):
            if link.get('rel') == 'next':
                url = link.get('href')
                break
        page += 1

    return None


def api_post(hatena_id, blog_id, api_key, xml_data):
    return requests.post(
        collection_url(hatena_id, blog_id),
        data=xml_data,
        headers=auth_headers(hatena_id, api_key),
    )


def api_put(edit_url, hatena_id, api_key, xml_data):
    return requests.put(
        edit_url,
        data=xml_data,
        headers=auth_headers(hatena_id, api_key),
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
    xml_data = build_entry_xml(title, body, hatena_id)

    # Dry-run: show and exit
    if args.dry_run:
        print(f'=== dry-run: {title} ({len(entries)} entries) ===')
        print(f'Title: {title}')
        print('Body:')
        print(body)
        return

    # Check for existing entry with the same title
    print(f'[{title}] Searching for existing entry...')
    edit_url = find_entry_edit_url(hatena_id, blog_id, api_key, title)

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
