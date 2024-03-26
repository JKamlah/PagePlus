from importlib import util
from collections import Counter
import re

import typer
from typing_extensions import Annotated

from pageplus.io.logger import logging
from pageplus.models.page import Page

if (spec := util.find_spec('spellchecker')):
    from spellchecker import SpellChecker

    class SpellCheckerPP(SpellChecker):
        """
        Spellchecer by Peter Norvig & Tyler Barrus! Extend for PagePlus needs.
        """
        @property
        def character_filter(self) -> str:
            return self.character_filter

        @character_filter.setter
        def character_filter(self, characterfilter: str) -> None:
            self.character_filter = characterfilter

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
                word_list.extend([re.sub(r"[" + re.escape(self.character_filter) + "]", '', key)
                                  for key, value in ws_dictionary.items()
                                  if len(key) > word_length and value > word_frequency
                                  and key[0].isupper()])
            # Additional words for dictionary
            # if I just want to make sure some words are not flagged as misspelled
            self._word_frequency._dictionary = Counter(word_list)
            self._word_frequency._update_dictionary()


        def check_page(self, page: Annotated[Page,
            typer.Option(help=f"Language of the dictionary: {SpellChecker().languages()}")] = None) -> None:
            """
            Spellcheck all lines on a page
            """
            for textregion in page.regions.textregions:
                for line in textregion.textlines:
                    text = line.get_text()
                    new_text = list()
                    for word in text.split():
                        # Remove punctuation
                        orig_word = word
                        mod_word = re.sub(r"[" + re.escape(self.character_filter) + "]", '', word)
                        word = self.correction(mod_word) if self.correction(mod_word) else mod_word
                        if mod_word.lower() != word.lower() and mod_word[-1] == word[-1]:
                            logging.info(f"Replaced: {mod_word} -> {word}")
                            new_text.append(word)
                        else:
                            new_text.append(orig_word)
                    line.update_text(' '.join(new_text))


