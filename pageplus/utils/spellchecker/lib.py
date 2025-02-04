from importlib import util
from collections import Counter
import re

import typer
from typing_extensions import Annotated, Pattern

from pageplus.io.logger import logging
from pageplus.models.page import Page

if (spec := util.find_spec('spellchecker')):
    from spellchecker import SpellChecker

    class SpellCheckerPP(SpellChecker):
        """
        Spellchecer by Peter Norvig & Tyler Barrus! Extend for PagePlus needs.
        """

        @property
        def ignore_last_character(self) -> bool:
            return self._ignore_last_character

        @ignore_last_character.setter
        def ignore_last_character(self, ignore_last_character_flag: bool) -> None:
            self._ignore_last_character = ignore_last_character_flag

        @property
        def leading_trailing_filter(self) -> str:
            return self._leading_trailing_filter

        @leading_trailing_filter.setter
        def leading_trailing_filter(self, leading_trailing_filter_string: str) -> None:
            self._leading_trailing_filter = leading_trailing_filter_string

        def leading_trailing_filter_pattern(self) -> Pattern[str]:
            return re.compile(r"^[" + re.escape(self.leading_trailing_filter) + "]+|[" + re.escape(self.leading_trailing_filter) + "]+$")

        def extend_dictionary(self, user_words: list, user_text: str, word_length: int, word_frequency: int):
            """
            Update dictionary with list of words or a text filtered by word length and frequency
            Args:
                user_words:
                user_text:
                word_length:
                word_frequency:
            Returns:
            """
            word_list = list(self._word_frequency._dictionary.keys())
            word_list.extend(user_words) if user_words else None
            if user_text != '':
                ws_dictionary = Counter(user_text.split())
                word_list.extend([re.sub(self.leading_trailing_filter_pattern(), '', key)
                                  for key, value in ws_dictionary.items()
                                  if len(key) > word_length and value > word_frequency
                                  and key[0].isupper()])
            # Additional words for dictionary
            # if I just want to make sure some words are not flagged as misspelled
            self._word_frequency._dictionary = Counter(word_list)
            self._word_frequency._update_dictionary()


        def check_page(self, page: Annotated[Page,
            typer.Option(help=f"Language of the dictionary: {SpellChecker().languages()}")] = None) -> Counter:
            """
            Spellcheck all lines on a page
            """
            replacements = Counter()
            for textregion in page.regions.textregions:
                for line in textregion.textlines:
                    text = line.get_text()
                    new_text = list()
                    for word in text.split():
                        # Remove punctuation
                        trimmed_word = re.sub(self.leading_trailing_filter_pattern(), '', word)
                        corrected_word = self.correction(trimmed_word) if self.correction(trimmed_word) else trimmed_word
                        if trimmed_word.lower() != corrected_word.lower() and (not self._ignore_last_character or trimmed_word[-1] == corrected_word[-1]):
                            logging.info(f"Replaced: {word} -> {word.replace(trimmed_word, corrected_word)}")
                            replacements.update([f"{word} -> {word.replace(trimmed_word, corrected_word)}"])
                            new_text.append(word.replace(trimmed_word, corrected_word))
                        else:
                            new_text.append(word)
                    line.update_text(' '.join(new_text))
            return replacements


