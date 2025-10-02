import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Dict
from collections import defaultdict

from pageplus.models.page import Page

COMBINING_CODEPOINTS = {
    *range(768, 879 + 1),
    *range(6832, 6848 + 1),
    *range(7616, 7664 + 1),
    *range(8400, 8432 + 1),
    *range(65056, 65071 + 1),
}


@dataclass
class LineAnalysis:
    """Holds analysis results for a single text line."""
    line_id: str
    text: str
    normalization_form: str

    normalized_text: str = field(init=False)
    glyphs: Counter = field(init=False)
    codepoints: Dict[int, int] = field(init=False)

    def __post_init__(self):
        self.normalized_text = unicodedata.normalize(self.normalization_form, self.text)
        self.glyphs = Counter(self.normalized_text)
        self.codepoints = {ord(glyph): val for glyph, val in self.glyphs.items()}


class FileAnalysis:
    """Holds analysis results for a single PAGE XML file."""

    def __init__(self, file_path: Path, normalization_form: str):
        self.path = file_path
        self.normalization_form = normalization_form
        self.page = Page(file_path)
        self.line_analyses: List[LineAnalysis] = self._analyze_lines()
        self._combined_glyphs: Counter | None = None

    def _analyze_lines(self) -> List[LineAnalysis]:
        return [
            LineAnalysis(line.get_id(), line.get_text(), self.normalization_form)
            for textregion in self.page.regions.textregions
            for line in textregion.textlines
        ]

    @property
    def texts(self) -> Dict[str, str]:
        return {la.line_id: la.normalized_text for la in self.line_analyses}

    @property
    def glyphs_per_line(self) -> Dict[str, Counter]:
        return {la.line_id: la.glyphs for la in self.line_analyses}

    @property
    def codepoints_per_line(self) -> Dict[str, Dict[int, int]]:
        return {la.line_id: la.codepoints for la in self.line_analyses}

    @property
    def total_glyphs(self) -> Counter:
        """Returns a counter with all glyphs in the file."""
        if not hasattr(self, '_total_glyphs'):
            self._total_glyphs = Counter()
            for la in self.line_analyses:
                self._total_glyphs.update(la.glyphs)
        return self._total_glyphs

    @property
    def total_codepoints(self) -> Dict[int, int]:
        """Returns a dictionary with all codepoints in the file."""
        if not hasattr(self, '_total_codepoints'):
            codepoints = defaultdict(int)
            for la in self.line_analyses:
                for code, count in la.codepoints.items():
                    codepoints[code] += count
            self._total_codepoints = dict(codepoints)
        return self._total_codepoints

    @staticmethod
    def _is_combining(char: str) -> bool:
        return ord(char) in COMBINING_CODEPOINTS

    @property
    def combined_glyphs(self) -> Counter:
        if self._combined_glyphs is None:
            combined = []
            for analysis in self.line_analyses:
                text = analysis.normalized_text
                for i, char in enumerate(text):
                    if i > 0 and self._is_combining(char):
                        combined.append(text[i - 1] + char)
            self._combined_glyphs = Counter(combined)
        return self._combined_glyphs
