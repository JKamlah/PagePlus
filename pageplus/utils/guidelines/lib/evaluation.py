import re
import unicodedata
from collections import defaultdict
import itertools
from typing import DefaultDict

from collections import Counter
import copy

from pageplus.utils.constants import GUIDELINES_DIR
from pageplus.utils.guidelines.lib.settings import load_profiles
from pageplus.utils.guidelines.lib.unicodecache import describe
from pageplus.utils.guidelines.lib.functools import get_defaultdict
from pageplus.utils.guidelines.lib.unicodetools import name_codepoints


def controlcharacter_check(glyph: str):
    """
    Checks if glyph is controlcharacter (unicodedata cant handle CC as input)
    :param glyph: unicode glyph
    :return:
    """
    if len(glyph) == 1 and (ord(glyph) < int(0x001F) or int(0x007F) <= ord(glyph) <= int(0x009F)):
        return True
    else:
        return False


def categorize(results: DefaultDict, category='combined') -> None:
    """
    Puts the unicode character in user-definied categories
    :param results: results instance
    :param category: category
    :return:
    """
    if category == 'combined':
        get_defaultdict(results[category], 'cat')
        for glyph, count in results[category]['all']['glyph'].items():
            if controlcharacter_check(glyph):
                uname, ucat, usubcat = "L", "S", "CC"
            else:
                uname, ucat, usubcat = describe(glyph)
            get_defaultdict(results[category]["cat"], ucat[0])
            get_defaultdict(results[category]["cat"][ucat[0]], usubcat)
            get_defaultdict(results[category]["cat"][ucat[0]][usubcat], ucat)
            results[category]["cat"][ucat[0]][usubcat][ucat].update({glyph: count})
    else:
        get_defaultdict(results["combined"], "usr")
        categories = load_profiles(
            (GUIDELINES_DIR / "profiles" / "evaluate" / "categories.json").as_posix()
        )
        if categories and category in categories.keys():
            get_defaultdict(results["combined"]["usr"], category)
            for glyph, count in results['combined']['all']['glyph'].items():
                for subcat, subkeys in categories[category].items():
                    for subkey in subkeys:
                        if controlcharacter_check(glyph):
                            uname = "ControlCharacter"
                        else:
                            uname = unicodedata.name(glyph)
                        if ord(glyph) == subkey or subkey in uname:
                            get_defaultdict(results["combined"]["usr"][category], subcat)
                            results["combined"]["usr"][category][subcat][glyph] = count
    return


def missing_unicode(results: DefaultDict, evalu, profile) -> None:
    """
    Puts the unicode character in user-definied categories
    :param results: results instance
    :param evalu: process handler
    :param profile: missing unicode profile
    :return:
    """
    get_defaultdict(results["combined"], "missing", list)
    missing_unicodes = load_profiles(
        (GUIDELINES_DIR / "profiles" / "evaluate" / "missing_unicode.json").as_posix()
    )
    uc_codepoints = set(results['combined']['all']['codepoints'].keys())
    uc_combinded_glyphs = set(results['combined']['all']['combined glyph'].keys())
    if missing_unicodes and profile in missing_unicodes.keys():
        get_defaultdict(results["combined"]["missing"], profile, list)
        check_unicode(results["combined"]["missing"][profile], missing_unicodes[profile], uc_codepoints,
                      uc_combinded_glyphs)
        if not bool([subval for subval in results["combined"]["missing"][profile].values() if subval != []]):
            results["combined"]["missing"][profile] = {f"All glyphs from '{profile}' were found!": []}
    else:
        if profile not in missing_unicodes.keys():
            evalu.print(f"'{profile}' was not found in the settings file")


def difference(fst_set, snd_set):
    return set(fst_set).difference(set(snd_set))


def intersection(fst_set, snd_set):
    return set(fst_set).intersection(set(snd_set))


def check_unicode(resdict, profiles, uc_codepoints, uc_combinded_glyphs, func='difference'):
    func = {'difference': difference, 'intersection': intersection}.get(func, difference)
    for subsetting, subvals in profiles.items():
        if subsetting.lower().startswith(('glyph', 'hex', 'codepoint')):
            resdict[subsetting].extend(func(subvals, uc_codepoints))
        elif subsetting.lower().startswith('combined'):
            resdict[subsetting].extend(func(subvals, uc_combinded_glyphs))
        else:
            for subval in subvals:
                if subsetting.lower().startswith('name'):
                    resdict[subsetting].extend(
                        func(name_codepoints(subval, regex='regex' in subsetting.lower()), uc_codepoints))
    return


def validate_with_guidelines(results: DefaultDict, evalu) -> None:
    """
    Validates each unicode character against the OCR-D or user-definded guidelines
    on a per-file, per-line basis.
    :param results: result instance
    :param evalu: arguments instance
    :return:
    """
    guideline = evalu.guideline
    guidelines = evalu.guidelines
    if not (guidelines and guideline in guidelines):
        return

    # Deep copy to avoid modifying the cached guidelines
    guideline_data = copy.deepcopy(guidelines[guideline])
    forbidden_rules = guideline_data.get('forbidden', {})
    exception_rules = guideline_data.get('exception', {})

    # Filter forbidden_rules by removing exceptions
    for rule_type, exceptions in exception_rules.items():
        if rule_type in forbidden_rules:
            forbidden_rules[rule_type] = [rule for rule in forbidden_rules[rule_type] if rule not in exceptions]
            # If a rule type becomes empty, remove it
            if not forbidden_rules[rule_type]:
                del forbidden_rules[rule_type]

    # This function will now only operate on single files.
    for file_idx, file_info in results.get('single', {}).items():
        filename = results['path_indexes'][file_idx]
        file_info['guideline_violations_summary'] = Counter()
        file_info['guideline_violations_details'] = []

        lines_text = file_info.get('details', {}).get('text', {})
        lines_codepoints_per_line = file_info.get('details', {}).get('codepoints_per_line', {})
        file_codepoints = set(file_info.get('all', {}).get('codepoints', {}).keys())
        file_combined_glyphs = set(file_info.get('all', {}).get('combined glyph', {}).keys())

        # Process filtered forbidden rules
        for conditionkey, conditions in forbidden_rules.items():
            if "regex" in conditionkey.lower():
                for condition in conditions:
                    for line_id, line_text in lines_text.items():
                        matches = re.findall(rf"{condition}", line_text)
                        if matches:
                            evalu.print(f"File: {filename.name}\n  Line: {line_id}\n  Rule: '{condition} ({conditionkey})'\n  Content: '{line_text}'\n  Match: {matches}\n")
                            rule = f"{condition} ({conditionkey})"
                            file_info['guideline_violations_summary'][rule] += len(matches)
                            file_info['guideline_violations_details'].append({
                                "line_id": line_id,
                                "rule": rule,
                                "content": line_text,
                                "match": matches
                            })
            else:  # Codepoint / Glyph validation
                violation_codepoints_for_file = defaultdict(list)
                check_unicode(violation_codepoints_for_file, {conditionkey: conditions}, file_codepoints, file_combined_glyphs, func='intersection')

                violating_codes = set(itertools.chain.from_iterable(violation_codepoints_for_file.values()))

                if violating_codes:
                    for line_id, codepoints_in_line in lines_codepoints_per_line.items():
                        line_violations = violating_codes.intersection(codepoints_in_line.keys())
                        if line_violations:
                            line_text = lines_text[line_id]
                            violating_glyphs = [chr(code) for code in line_violations]
                            for violating_glyph in violating_glyphs:
                                occurrences = codepoints_in_line.get(ord(violating_glyph), 0)
                                if occurrences == 0:
                                    continue

                                evalu.print(f"""File: {filename.name}\n  Line: {line_id}\n  Rule: '{violating_glyph} ({conditionkey})'\n
Content: '{line_text}'\n  Violation: {violating_glyph} (occurs {occurrences} times)\n""")

                                # Storing result for summary
                                rule = f"{violating_glyph} ({conditionkey})"
                                file_info['guideline_violations_summary'][rule] += occurrences
                                file_info['guideline_violations_details'].append({
                                    "line_id": line_id,
                                    "rule": rule,
                                    "content": line_text,
                                    "violation": violating_glyph,
                                    "occurrences": occurrences
                                })
