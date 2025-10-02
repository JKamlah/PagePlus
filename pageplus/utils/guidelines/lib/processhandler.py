from collections import defaultdict, Counter
from pathlib import Path
from typing import List
import re

from pageplus.utils.guidelines.lib.io import open_stream_to
from pageplus.utils.guidelines.lib.settings import load_profiles
from pageplus.utils.constants import GUI_STORAGE_DIR, GUIDELINES_DIR


def merge_guidelines(default_data, user_data):
    """Recursively merges user data into default data."""
    if isinstance(default_data, dict) and isinstance(user_data, dict):
        for key, value in user_data.items():
            if key in default_data and isinstance(default_data[key], dict) and isinstance(value, dict):
                default_data[key] = merge_guidelines(default_data[key], value)
            else:
                default_data[key] = value
        return default_data
    return user_data


class Handler:
    def __init__(self, fnames: List[str], output: str,):
        self.files = fnames
        self.output = output

    def num_filenames(self):
        return len(self.files)

    def print(self, msg):
        print(msg)


class Evaluatehandler(Handler):

    def __init__(self, fnames, output, json, custom_categories, statistical_categories,
                 addinfo, guideline, textnormalization,
                 report_data=None, report_data_format=None):
        super().__init__(fnames, output)
        self.fout = None
        self.orig_fname = None
        self.json = json
        self.statistical_categories = statistical_categories
        self.custom_categories = custom_categories
        self.addinfo = addinfo
        self.logging = None

        self.report_data = report_data
        self.report_data_format = report_data_format

        self.guideline = guideline
        if self.guideline:
            if self.guideline != 'CUSTOM':
                default_guidelines_path = GUIDELINES_DIR / "profiles" / "guidelines.json"
                user_guidelines_path = GUI_STORAGE_DIR / "guidelines" / "profiles" / "guidelines.json"

                default_guidelines = load_profiles(default_guidelines_path.as_posix()) if default_guidelines_path.exists() else {}
                user_guidelines = load_profiles(user_guidelines_path.as_posix()) if user_guidelines_path.exists() else {}

                self.guidelines = merge_guidelines(default_guidelines, user_guidelines)
            else:
                # TODO: Implement custom guidelines
                # guidelinespath = ""
                self.guidelines = {}
        else:
            self.guidelines = {}
        self.textnormalization = textnormalization
        self.guideline_file = ""


class Mappinghandler(Handler):
    def __init__(self, fnames, guideline, textnormalization, substitutiontext=None):
        super().__init__(fnames, output=None)
        self.filecounter = 0
        self.logging = None
        self.substitutiontext = substitutiontext
        self.guideline = guideline
        self.replacement_counts = defaultdict(lambda: defaultdict(Counter))
        if self.guideline:
            if self.guideline != 'CUSTOM':
                default_mappings_path = GUIDELINES_DIR / "profiles" / "mappings.json"
                user_mappings_path = GUI_STORAGE_DIR / "guidelines" / "profiles" / "mappings.json"

                default_mappings = load_profiles(default_mappings_path.as_posix()) if default_mappings_path.exists() else {}
                user_mappings = load_profiles(user_mappings_path.as_posix()) if user_mappings_path.exists() else {}

                self.guidelines = merge_guidelines(default_mappings, user_mappings)
            else:
                # TODO: Implement custom guidelines
                # guidelinespath = ""
                self.guidelines = {}
        else:
            self.guidelines = {}
        self.textnormalization = textnormalization
        self.guideline_file = ""

    def mapping_by_guideline(self, text: str, line_id: str, filename: str, mode: str = 'deterministic'):
        """
        Maps a text string based on the rules in the guideline profile.

        Args:
            text (str): The text to normalize.
            line_id (str): The ID of the text line being processed.
            filename (str): The name of the file being processed.

        Returns:
            str: The normalized text.
        """
        if not self.guideline or not self.guidelines:
            return text

        profile = self.guidelines.get(self.guideline)
        if not profile:
            return text
        for rule_name, rule_data in profile.get(mode, {}).items():
            for rule_mode, mappings in rule_data.items():
                for mapping in mappings:
                    try:
                        print(mapping)
                        if mapping['from'] == mapping['to']:
                            continue
                        if rule_mode == 'regex':
                            text, num_replacements = re.subn(mapping['from'], mapping['to'], text)
                            if num_replacements > 0:
                                self.replacement_counts[filename][rule_name][line_id] += num_replacements
                        else:
                            num_replacements = text.count(mapping['from'])
                            if num_replacements > 0:
                                text = text.replace(mapping['from'], mapping['to'])
                                self.replacement_counts[filename][rule_name][line_id] += num_replacements
                    except re.error:
                        continue
        return text

    def update_logger(self):
        self.logging = open_stream_to(self.logging, Path(self.current_file.joinpath("substitution.log")))

    def close_logger(self):
        # close stream to log files
        self.logging.close()

    @staticmethod
    def write_log(logging, msg):
        if logging:
            logging.write(msg)
            logging.flush()
