from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from pageplus.io.logger import logging


@dataclass
class PageCounter:
    textregions: int = 0
    tableregions: int = 0
    textlines: int = 0
    words: int = 0
    glyphs: int = 0

    def statistics(self, pre_text: str = "") -> None:
        """
        Logs the statistics of the page elements.
        """
        log_message = f"{pre_text}\n" if pre_text else ""
        log_message += (f"Overall textregions:  {self.textregions}\n"
                        f"Overall tableregions: {self.tableregions}\n"
                        f"Overall lines:        {self.textlines}\n"
                        f"Overall words:        {self.words}\n"
                        f"Overall glyphs:       {self.glyphs}")
        logging.info(log_message)

    def __add__(self, other: PageCounter) -> PageCounter:
        """
        Adds the counts of another PageCounter instance to this instance.
        """
        if not isinstance(other, PageCounter):
            raise TypeError("Operand must be an instance of PageCounter")
        self.textregions += other.textregions
        self.tableregions += other.tableregions
        self.textlines += other.textlines
        self.words += other.words
        self.glyphs += other.glyphs
        return self


@dataclass
class SubCounter:
    subs: Counter = None

    def statistics(self, pre_text: str = "") -> None:
        if pre_text != "":
            pre_text += "\n"
        logging.info(f"{pre_text}"
                     f"Overall substitution count\n"
                     f"{self.subs.total()}\n"
                     f"All substitutions\n" + '\n'.join([f'{k}: \t{v:04d}' for k, v in self.subs.most_common()]))

    def __add__(self, other: SubCounter) -> SubCounter:
        if isinstance(other, SubCounter):
            self.subs.update(other.subs)
        return self
