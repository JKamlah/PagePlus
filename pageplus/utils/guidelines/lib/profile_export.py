"""Utilities for exporting GTReval profiles to choco-mufin compatible tables."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Optional

from pageplus.utils.guidelines.lib.settings import load_profiles
from pageplus.utils.guidelines.lib.unicodetools import name_codepoints
from pageplus.utils.guidelines.lib.unicodecache import get_name

FIELDNAMES = [
    'char',
    'replacement',
    'regex',
    'allow',
    'profile',
    'rule',
    'source',
    'codepoint',
    'name',
]


def export_profile_to_csv(profile_path: Path, output_dir: Path, overwrite: bool = False) -> List[Path]:
    """Convert a profile definition into one CSV file per section.

    Parameters
    ----------
    profile_path:
        Path to the original GTReval profile (INI-like text file).
    output_dir:
        Directory where the generated CSV files should be written. A subdirectory
        matching the profile file stem is created automatically.
    overwrite:
        Replace existing CSV files if they are already present.

    Returns
    -------
    List[Path]
        Paths of the generated CSV files.
    """

    profile_path = Path(profile_path)
    if not profile_path.exists():
        raise FileNotFoundError(profile_path)

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    target_dir = output_dir.joinpath(profile_path.stem)
    target_dir.mkdir(parents=True, exist_ok=True)

    profiles = load_profiles(profile_path.as_posix())
    generated_files: List[Path] = []

    for section, rules in profiles.items():
        rows = _build_rows(section, rules)
        if not rows:
            continue
        dest_file = target_dir.joinpath(f"{section}.csv")
        if dest_file.exists() and not overwrite:
            raise FileExistsError(dest_file)
        with dest_file.open('w', encoding='utf-8', newline='') as fout:
            writer = csv.DictWriter(
                fout,
                fieldnames=FIELDNAMES,
                quoting=csv.QUOTE_MINIMAL,
                escapechar='\\',
            )
            writer.writeheader()
            writer.writerows(rows)
        generated_files.append(dest_file)

    return generated_files


def _build_rows(section: str, rules: Dict) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    for rule, values in rules.items():
        glyph_entries = _expand_rule(section, rule, values)
        rows.extend(glyph_entries)
    return rows


def _expand_rule(section: str, rule: str, values: Iterable) -> List[Dict[str, str]]:
    rule_lower = rule.lower()
    entries: Dict[str, Dict[str, str]] = {}

    if rule_lower.startswith('regex'):
        rows = []
        for pattern in values:
            rows.append({
                'char': pattern,
                'replacement': '',
                'regex': 'true',
                'allow': 'true',
                'profile': section,
                'rule': rule,
                'source': pattern,
                'codepoint': '',
                'name': '',
            })
        return rows

    for entry in _expand_values(rule_lower, values):
        if entry is None:
            continue
        char = entry['char']
        data = entries.setdefault(char, {
            'char': char,
            'replacement': '',
            'regex': '',
            'allow': 'true',
            'profile': section,
            'rule': rule,
            'source': set(),
            'codepoint': entry['codepoint'],
            'name': entry['name'],
        })
        data['source'].add(entry['source'])
        if not data['codepoint']:
            data['codepoint'] = entry['codepoint']
        if not data['name']:
            data['name'] = entry['name']

    rows = []
    for data in entries.values():
        sources = sorted(data['source'])
        data['source'] = ' | '.join(sources)
        rows.append(data)
    return rows


def _expand_values(rule_lower: str, values: Iterable) -> Iterator[Optional[Dict[str, str]]]:
    for value in values:
        for entry in _expand_value(rule_lower, value):
            yield entry


def _expand_value(rule_lower: str, value) -> List[Dict[str, str]]:
    entries: List[Dict[str, str]] = []

    if isinstance(value, list):
        for item in value:
            entries.extend(_expand_value(rule_lower, item))
        return entries

    if isinstance(value, range):
        for item in value:
            entries.extend(_expand_value(rule_lower, item))
        return entries

    if isinstance(value, int):
        try:
            glyph = chr(value)
        except ValueError:
            return entries
        entry = _make_entry(glyph, f"{rule_lower}: U+{value:04X}")
        if entry:
            entries.append(entry)
        return entries

    value_str = str(value)

    if rule_lower.startswith('name'):
        regex = 'regex' in rule_lower
        codepoints = name_codepoints(value_str, regex=regex)
        for codepoint in codepoints:
            try:
                glyph = chr(codepoint)
            except ValueError:
                continue
            qualifier = 'name regex' if regex else 'name'
            entry = _make_entry(glyph, f"{qualifier}: {value_str}")
            if entry:
                entries.append(entry)
        return entries

    if rule_lower.startswith('block'):
        # NOTE: Block, script, and property lookups are not supported by unicodedataplus directly.
        # This functionality will be removed. For now, it will return an empty list.
        return []

    if rule_lower.startswith('script'):
        # NOTE: Block, script, and property lookups are not supported by unicodedataplus directly.
        return []

    if rule_lower.startswith('property'):
        # NOTE: Block, script, and property lookups are not supported by unicodedataplus directly.
        return []

    if rule_lower.startswith('combined'):
        glyph = value_str
        entry = _make_entry(glyph, f"combined glyph: {value_str}")
        if entry:
            entries.append(entry)
        return entries

    if rule_lower.startswith('hex'):
        try:
            codepoint = int(value_str, 16)
            glyph = chr(codepoint)
        except (ValueError, TypeError):
            return entries
        entry = _make_entry(glyph, f"hex: {value_str}")
        if entry:
            entries.append(entry)
        return entries

    if rule_lower.startswith('codepoint'):
        try:
            codepoint = int(value_str)
            glyph = chr(codepoint)
        except (ValueError, TypeError):
            return entries
        entry = _make_entry(glyph, f"codepoint: {value_str}")
        if entry:
            entries.append(entry)
        return entries

    if rule_lower.startswith('glyph'):
        glyph = value_str
        entry = _make_entry(glyph, f"glyph: {value_str}")
        if entry:
            entries.append(entry)
        return entries

    # Fallback to raw string representation
    glyph = value_str
    entry = _make_entry(glyph, f"{rule_lower}: {value_str}")
    if entry:
        entries.append(entry)
    return entries


def _make_entry(glyph: str, source: str) -> Optional[Dict[str, str]]:
    if any(ord(ch) < 32 for ch in glyph):
        return None
    codepoint = _codepoint_string(glyph)
    name = _name_string(glyph)
    return {
        'char': glyph,
        'replacement': '',
        'regex': '',
        'allow': 'true',
        'profile': '',  # filled by caller
        'rule': '',      # filled by caller
        'source': source,
        'codepoint': codepoint,
        'name': name,
    }


def _codepoint_string(glyph: str) -> str:
    return ' '.join(f"U+{ord(ch):04X}" for ch in glyph)


def _name_string(glyph: str) -> str:
    names = [get_name(ch) or "" for ch in glyph]
    return ' + '.join([name for name in names if name])


def _flatten_codepoints(items: Iterable) -> Iterator[int]:
    for item in items:
        if isinstance(item, int):
            yield item
        elif isinstance(item, range):
            for sub in item:
                yield sub
        elif isinstance(item, (list, tuple, set)):
            for sub in _flatten_codepoints(item):
                yield sub
