import csv
import json
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path
from typing import DefaultDict, Dict, Iterable, List, Optional

from pageplus.utils.guidelines.lib.evaluation import controlcharacter_check
from pageplus.utils.guidelines.lib.functools import get_defaultdict
from pageplus.utils.guidelines.lib.unicodecache import get_name


class ReportCollector(object):
    """Collects structured entries while rendering the textual report."""

    __slots__ = ("records",)

    def __init__(self):
        self.records: List[Dict[str, object]] = []

    def add_record(self, record: Dict[str, object]) -> None:
        self.records.append(record)

    def __len__(self) -> int:
        return len(self.records)

    def as_records(self) -> List[Dict[str, object]]:
        return list(self.records)

    def to_json(self) -> List[Dict[str, object]]:
        return self.as_records()

    def to_dataframe(self):  # pragma: no cover - pandas optional dependency
        try:
            import pandas as pd
        except ImportError as exc:  # pragma: no cover - executed only when pandas missing
            raise RuntimeError("pandas is required to build a dataframe") from exc
        return pd.DataFrame(self.records)


def _codepoints_for_glyph(glyph: str) -> List[str]:
    return [f"U+{ord(char):04X}" for char in glyph]


def print_unicodeinfo(evalu, val, key, collector: Optional[ReportCollector] = None,
                      context: Optional[Dict[str, object]] = None) -> str:
    """
    Prints the occurrence, unicode character or guideline rules and additional information
    :param evalu: process handler
    :param val: count of the occurrences of key
    :param key: key (glyph or guideline rules)
    :param collector: optional report collector for structured exports
    :param context: additional metadata about the current section
    :return:
    """
    glyph = key
    if isinstance(key, int):
        glyph = chr(key)
    if not isinstance(glyph, str):
        glyph = str(glyph)

    glyph_display = repr(glyph) if controlcharacter_check(glyph) else glyph
    normalized_pair = None

    if isinstance(val, int):
        line = f"\u200E{val:-{6}}  {{" + f"{glyph_display}" + "}" + addinfo(evalu, glyph)
        codepoints = _codepoints_for_glyph(glyph)
        numeric_value = val
    elif isinstance(val, str) and len(unicodedata.normalize('NFD', val)) == 2:
        normalized_pair = unicodedata.normalize('NFD', val)
        first, second = normalized_pair[0], normalized_pair[1]
        line = (f"\u200E{{{glyph_display}}} "
                f"U+{str(hex((ord(first)))).replace('0x', '').zfill(4)}-"
                f"U+{str(hex((ord(second)))).replace('0x', '').zfill(4)} "
                f"{addinfo(evalu, normalized_pair)}")
        codepoints = [f"U+{str(hex(ord(first))).replace('0x', '').zfill(4).upper()}",
                      f"U+{str(hex(ord(second))).replace('0x', '').zfill(4).upper()}"]
        numeric_value = None
    else:
        hex_repr = str(val)
        try:
            decimal_val = int(hex_repr, 16)
        except (TypeError, ValueError):
            decimal_val = hex_repr
        formatted_hex = hex_repr.replace('0x', '').zfill(4)
        line = (f"\u200E{{{glyph_display}}} "
                f"U+{formatted_hex.upper()} {decimal_val}{addinfo(evalu, glyph)}")
        codepoints = [f"U+{formatted_hex.upper()}"]
        numeric_value = decimal_val if isinstance(decimal_val, int) else None

    if collector is not None and context is not None:
        record = {
            'section': context.get('section'),
            'subsection': context.get('subsection'),
            'condition': context.get('condition'),
            'group': context.get('group'),
            'glyph': glyph,
            'text': line.strip(),
            'value': val,
            'count': val if isinstance(val, int) else None,
            'numeric_value': numeric_value,
            'codepoints': codepoints,
        }
        if normalized_pair:
            record['normalized_pair'] = normalized_pair
        collector.add_record(record)
    # The \u200E is the LR Mark so the text is rendered from left to right even if the next symbol is RL
    return line


def addinfo(evalu, key) -> str:
    """
    Adds info to the single unicode statistics like the hexa code or the unicodename
    :param evalu: arguments instance
    :param key: key string (glyphs or guideline rules)
    :return:
    """
    info = ' '
    if len(key) > 1:
        if len(key) == 2:
            if 'code' in evalu.addinfo:
                try:
                    info += f"{str(hex(ord(key[0])))} - {str(hex(ord(key[1])))} "
                except ValueError:
                    info += f"NO NAME IS AVAILABLE FOR {key}"
            if 'name' in evalu.addinfo:
                name_first = get_name(key[0])
                name_second = get_name(key[1])
                if name_first and name_second:
                    info += f"{name_first} - {name_second}"
                else:
                    info += f"NO NAME IS AVAILABLE FOR {key}"
        elif controlcharacter_check(key):
            return info + "CONTROL CHARACTER"
    else:
        if 'code' in evalu.addinfo:
            info += str(hex(ord(key))) + " "
        if 'name' in evalu.addinfo:
            name = get_name(key)
            if name:
                info += name
            else:
                info += f"NO NAME IS AVAILABLE FOR {str(hex(ord(key)))}"
    return info.rstrip()


def report_subsection(fout, subsection: str, result: DefaultDict, evalu, header='', subheaderinfo='',
                      collector: Optional[ReportCollector] = None) -> None:
    """
    Creats subsection reports
    :param fout: name of the outputfile
    :param subsection: name of subsection
    :param result: result instance
    :param evalu: process handler
    :param header: header info string
    :param subheaderinfo: subheader info string
    :return:
    """
    addline = '\n'
    fout.write(f"""
    {header}
    {subheaderinfo}{addline if subheaderinfo != '' else ''}""")
    if not result:
        fout.write(f"""{"-" * 60}\n""")
        return
    header_label = header.strip()
    for condition, conditionres in result[subsection].items():
        fout.write(f"""
        {condition.capitalize()}
        {"-" * len(condition)}""")
        base_context = {
            'section': header_label or subsection,
            'subsection': subsection,
            'condition': condition,
        }
        if isinstance(conditionres, list):
            if not conditionres:
                continue
            for subval in sorted(conditionres):
                if isinstance(subval, int):
                    formatted = print_unicodeinfo(evalu, str(hex(subval)), chr(subval),
                                                  collector=collector, context=base_context)
                else:
                    formatted = print_unicodeinfo(evalu, subval, subval,
                                                  collector=collector, context=base_context)
                fout.write(f"""
                         {formatted}""")
        else:
            for key, val in conditionres.items():
                if isinstance(val, list):
                    if not val:
                        continue
                    for subval in sorted(val):
                        context = dict(base_context)
                        context['group'] = str(key)
                        formatted = print_unicodeinfo(evalu, str(hex(subval)), chr(subval),
                                                      collector=collector, context=context)
                        fout.write(f"""
                             {formatted}""")
                elif isinstance(val, dict):
                    fout.write(f"""
                {key}:""")
                    context = dict(base_context)
                    context['group'] = str(key)
                    for subkey, subval in sorted(val.items()):
                        if isinstance(subkey, int):
                            glyph = chr(subkey)
                        elif isinstance(subkey, str) and len(subkey) == 1:
                            glyph = subkey
                        else:
                            glyph = chr(subkey) if isinstance(subkey, int) else str(subkey)
                        formatted = print_unicodeinfo(evalu, subval, glyph,
                                                      collector=collector, context=context)
                        fout.write(f"""
                                {formatted}""")
                else:
                    context = dict(base_context)
                    context['group'] = str(key)
                    glyph = chr(key) if isinstance(key, int) else key
                    formatted = print_unicodeinfo(evalu, val, glyph,
                                                  collector=collector, context=context)
                    fout.write(f"""
                            {formatted}""")
    fout.write(f"""
    \n{"-" * 60}\n""")
    return


def sum_statistics(result: DefaultDict, section: str) -> int:
    """
    Sums up all occrurences
    :param result: result instance
    :param section: section to sum
    :return:
    """
    return sum([val for subsection in result[section].values() for val in subsection.values()])


def summarize(results: DefaultDict, category: str) -> None:
    """
    Summarizes the results of multiple input data
    :param results: results instance
    :param category: category
    :return:
    """
    if category in results:
        get_defaultdict(results, 'sum')
        results['sum']['sum'] = results['sum'].get('sum', 0)
        get_defaultdict(results['sum'], category)
        results['sum'][category]['sum'] = 0
        for sectionkey, sectionval in results[category].items():
            get_defaultdict(results['sum'][category], sectionkey)
            results['sum'][category][sectionkey]['sum'] = 0
            if isinstance(list(sectionval.values())[0], dict):
                for subsectionkey, subsectionval in sorted(sectionval.items()):
                    get_defaultdict(results['sum'][category][sectionkey], subsectionkey)
                    intermediate_sum = sum(subsectionval.values())
                    results['sum'][category][sectionkey][subsectionkey]['sum'] = intermediate_sum
                    results['sum'][category][sectionkey]['sum'] += intermediate_sum
                    results['sum'][category]['sum'] += intermediate_sum
                    results['sum']['sum'] += intermediate_sum
            else:
                intermediate_sum = sum(sectionval.values())
                results['sum'][category][sectionkey]['sum'] = intermediate_sum
                results['sum'][category]['sum'] += intermediate_sum
                results['sum']['sum'] += intermediate_sum
    return


def get_nested_val(ndict, keys, default=0):
    """
    Returns a value or the default value for a key in a nested dictionary
    :param ndict: nested dict instance
    :param keys: keys
    :param default: default value
    :return:
    """
    # TODO: Maybe it is faster with try (ndict[allkeys]) and except (default)..
    val = default
    for key in keys:
        val = ndict.get(key, default)
        if isinstance(val, dict):
            ndict = val
        elif val == 0:
            return val
    return val


def _create_single_report_section(fout, data, title, evalu, collector: Optional[ReportCollector] = None):
    """
    Creates a report section for a single file or for the combined results.
    """
    fpoint = 10
    fout.write(f"""
    {title}
    {"-" * len(title)}""")

    if 'cat' in data and 'sum' in data['cat']:
        subheader = f"""
        {get_nested_val(data, ['cat', 'sum', 'Z', 'SPACE', 'Zs', 'sum']):-{fpoint}} ASCII Spacing Symbols
        {get_nested_val(data, ['cat', 'sum', 'N', 'DIGIT', 'Nd', 'sum']):-{fpoint}} ASCII Digits
        {get_nested_val(data, ['cat', 'sum', 'L', 'LATIN', 'sum']):-{fpoint}} ASCII Letters
        {get_nested_val(data, ['cat', 'sum', 'L', 'LATIN', 'Ll', 'sum']):-{fpoint}} ASCII Lowercase Letters
        {get_nested_val(data, ['cat', 'sum', 'L', 'LATIN', 'Lu', 'sum']):-{fpoint}} ASCII Uppercase Letters
        {get_nested_val(data, ['cat', 'sum', 'P', 'sum']):-{fpoint}} Punctuation & Symbols
        {get_nested_val(data, ['cat', 'sum', 'sum']):-{fpoint}} Total Glyphs
    """
        report_subsection(fout, 'L', defaultdict(str), evalu, header='Statistics',
                          subheaderinfo=subheader, collector=collector)

    # Re-add guideline violation summary to the text report
    if 'guideline_violations_summary' in data and data['guideline_violations_summary']:
        violations = sum(data['guideline_violations_summary'].values())
        summary_dict = defaultdict(dict)
        summary_dict[evalu.guideline] = {'Violations': data['guideline_violations_summary']}
        report_subsection(fout, evalu.guideline, summary_dict, evalu,
                          header=f"{evalu.guideline} Guidelines Evaluation",
                          subheaderinfo=f"Total guideline violations: {violations}",
                          collector=collector)

    if 'usr' in data:
        for category in evalu.custom_categories:
            if category and category in data['usr']:
                occurrences = sum_statistics(data['usr'], category)
                report_subsection(fout, category, data['usr'], evalu,
                                  header=f"Category statistics: {category}",
                                  subheaderinfo=f"Overall occurrences: {occurrences}",
                                  collector=collector)

    if 'all' in data:
        if 'all' in evalu.statistical_categories:
            data['all']['glyph'] = dict(data['all']['glyph'].most_common())
            report_subsection(fout, 'all', data, evalu,
                              header='Unicode glyph statistics', collector=collector)

    if 'cat' in data:
        for cat in set(evalu.statistical_categories).intersection(set(data['cat'].keys())):
            if cat in ['all', 'sum']:
                continue
            report_subsection(fout, cat, data['cat'], evalu, header={'L': 'Letter statistics',
                                                                                 'Z': 'Separator statistics',
                                                                                 'P': 'Punctuation statistics',
                                                                                 'M': 'Mark statistics',
                                                                                 'N': 'Number statistics',
                                                                                 'S': 'Symbol statistics',
                                                                                 'C': 'Other statistics'}.get(cat),
                              collector=collector)

    if 'missing' in data:
        for cat in data['missing']:
            report_subsection(fout, cat, data['missing'], evalu,
                              header=f"Missing characters for profile '{cat}'",
                              collector=collector)


def create_report(result: DefaultDict, evalu, collector: Optional[ReportCollector] = None) -> Optional[Iterable[Dict[str, object]]]:
    """
    Creates the report
    :param result: results instance
    :param evalu: evaluation processhandler
    :return:
    """
    fnames = '; '.join(set([str(fpath.resolve()) for fpath in evalu.files]))

    if not evalu.output:
        evalu.fout = sys.stdout
    else:
        evalu.fout = open(evalu.output, 'w')

    evalu.fout.write(f"""
    Analyse-Report Version 0.1
    Input: {fnames}
    \n{"-" * 60}\n""")

    # Report for each file
    if 'single' in result:
        for i, file_data in result['single'].items():
            file_path = result['path_indexes'][i]
            _create_single_report_section(evalu.fout, file_data, f"File: {file_path}", evalu, collector)

    # Combined report
    if 'combined' in result:
        _create_single_report_section(evalu.fout, result['combined'], "Combined Results", evalu, collector)

    evalu.fout.flush()
    if evalu.fout != sys.stdout:
        evalu.fout.close()
    if collector is not None:
        return collector.as_records()
    return None


def write_structured_report(records: Iterable[Dict[str, object]], destination, fmt: Optional[str] = None) -> None:
    """Persist structured report records as JSON or CSV."""

    dest_path = Path(destination)
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    fmt = (fmt or dest_path.suffix.lstrip('.')).lower() if dest_path.suffix else (fmt or 'json')
    if fmt == '':
        fmt = 'json'
    if fmt not in {'json', 'csv'}:
        raise ValueError(f"Unsupported structured report format '{fmt}'")

    records = list(records)

    if fmt == 'json':
        with dest_path.open('w', encoding='utf-8') as fout:
            json.dump(records, fout, indent=2, ensure_ascii=False)
        return

    # CSV output
    flattened: List[Dict[str, object]] = []
    for record in records:
        row = {}
        for key, value in record.items():
            if isinstance(value, list):
                row[key] = ' '.join(str(item) for item in value)
            elif isinstance(value, dict):
                row[key] = json.dumps(value, ensure_ascii=False)
            else:
                row[key] = value
        flattened.append(row)

    fieldnames = sorted({field for row in flattened for field in row.keys()})
    with dest_path.open('w', encoding='utf-8', newline='') as fout:
        writer = csv.DictWriter(fout, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(flattened)
