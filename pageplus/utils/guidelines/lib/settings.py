import json
from collections import defaultdict
from functools import lru_cache
from pathlib import Path


@lru_cache()
def load_profiles(fname: str):
    """
    Loads the profiles into a dict
    :param fname: name of the profile file
    :return:
    """
    fin_path = Path(fname)
    if not fin_path.exists():
        raise FileNotFoundError(fin_path)

    if fin_path.suffix != '.json':
        raise ValueError(f"Only JSON profile files are supported ({fin_path})")

    with fin_path.open('r', encoding='utf-8') as fin:
        data = json.load(fin)

    name = fin_path.name
    if name == 'mappings.json':
        return _load_replacement_profiles(data)
    if name == 'guidelines.json':
        return _load_validation_profiles(data)
    if name == 'categories.json':
        return _load_category_profiles(data)
    if name == 'missing_unicode.json':
        return _load_missing_unicode_profiles(data)

    raise ValueError(f"Unsupported JSON profile structure in {fin_path}")


def _load_replacement_profiles(data):
    guidelines = defaultdict(lambda: defaultdict(dict))

    rules_index = data.get('rules', {})
    profiles = data.get('profiles', {})
    for profile_name, profile_data in profiles.items():
        profile_rules = profile_data.get('rules', {})
        for category, rule_names in profile_rules.items():
            rule_bucket = rules_index.get(category, {})
            for rule_name in rule_names:
                rule = rule_bucket.get(rule_name)
                if not rule or not rule.get('mappings'):
                    continue
                guidelines[profile_name][category][rule_name] = {rule.get('mode', 'unicode'): rule.get('mappings', [])}
    return guidelines


def _convert_unicode_mapping(value):
    if len(value) == 1:
        return [ord(value)]
    return [value]


def _load_validation_profiles(data):
    guidelines = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))

    rules_index = data.get('rules', {})
    profiles = data.get('profiles', {})

    for profile_name, profile_data in profiles.items():
        profile_rules = profile_data.get('rules', {})
        for category, rule_names in profile_rules.items():
            rule_bucket = rules_index.get(category, {})
            for rule_name in rule_names:
                rule = rule_bucket.get(rule_name)
                if not rule:
                    continue
                for source in rule.get('sources', []):

                    for key, values in source.items():
                        convert_key = key if key in ['regex', 'hex', 'codepoint', 'glyph'] else 'unicode'
                        for value in values:
                            guidelines[profile_name][category][key].extend(read_subsettings(convert_key, value))
    return guidelines


def _load_category_profiles(data):
    categories = defaultdict(lambda: defaultdict(list))
    for category_name, info in data.get('categories', {}).items():
        rules = info.get('rules', {})
        for key, values in rules.items():
            categories[category_name][key].extend(values)
    return categories


def _load_missing_unicode_profiles(data):
    profiles = defaultdict(lambda: defaultdict(list))
    for profile_name, info in data.get('profiles', {}).items():
        rules = info.get('rules', {})
        for key, values in rules.items():
            for value in values:
                profiles[profile_name][key].extend(read_subsettings(key, value))
    return profiles


def read_subsettings(subsetting, value):
    if subsetting.lower().startswith('regex'):
        return [value]
    if subsetting.lower().startswith('unicode'):
        if '-' in value and len(value) > 1 and len(value.split('-')) == 2:
            return [range(*sorted([int(val) if '0x' not in val else int(val, 16) for val in value.split('-')]))]
        else:
            if len(value) == 1:
                return [ord(value)]
            elif value.startswith('0x'):
                return [int(value, 16)]
            else:
                return [value]
    if subsetting.lower().startswith('combined'):
        if len(value) == 2:
            return [value]
    if subsetting.lower().startswith('glyph'):
        if '-' in value and len(value) > 1 and len(value.split('-')) == 2:
            return list(range(*[ord(val) for val in value.split('-')]))
        else:
            return [ord(value)]
    elif subsetting.lower().startswith('hex'):
        if '-' in value and len(value) > 1 and len(value.split('-')) == 2:
            start, end = value.split('-')
            if start.strip().startswith('0x') and end.strip().startswith('0x'):
                return list(range(int(start.strip(), 16), int(end.strip(), 16)))
        else:
            return [int(value, 16)]
    elif subsetting.lower().startswith('codepoint'):
        if '-' in value and len(value) > 1 and len(value.split('-')) == 2:
            start, end = value.split('-')
            if start.isdigit() and end.isdigit():
                return list(range(int(start.strip()), int(end.strip())))
        else:
            return [int(value)]
    else:
        return [value]
