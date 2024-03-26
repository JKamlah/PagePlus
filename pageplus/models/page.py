from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Tuple, Optional, List
from collections import Counter, defaultdict

import lxml.etree as ET
from shapely.geometry import LinearRing, Polygon, MultiPoint

from pageplus.io.parser import parse_xml
from pageplus.io.writer import write_xml
from pageplus.models.table_elements import TableRegion
from pageplus.models.text_elements import TextRegion


@dataclass
class Regions:
    textregions: Optional[List[TextRegion]] = field(default=None)
    tableregions: Optional[List[TableRegion]] = field(default=None)


@dataclass
class Page:
    filename: Path
    tree: Optional[ET._ElementTree] = field(default=None)
    root: Optional[ET.Element] = field(default=None)
    ns: Optional[str] = field(default=None)
    regions: Regions = field(default_factory=Regions)

    def __post_init__(self):
        """
        Initializes the Page object by loading XML data and populating regions.
        """
        if self.tree is None or self.root is None:
            self.tree, self.root, self.ns = self._open_xml(self.filename)

        text_region_xpath = f"{{{self.ns}}}TextRegion"
        self.regions.textregions = [TextRegion(ele, self.ns, parent=self) \
                                    for ele in self.root.iter(text_region_xpath)]

        table_region_xpath = f"{{{self.ns}}}TableRegion"
        self.regions.tableregions = [TableRegion(ele, self.ns, parent=self) \
                                     for ele in self.root.iter(table_region_xpath)]

    def get_region_reading_order_ids(self, mode: str = 'auto'):
        ro_ids = []
        if mode in ['auto', 'reading_order']:
            reading_order = self.tree.find(f".//{{{self.ns}}}ReadingOrder")
            if reading_order is not None:
                # Process each group in the reading order
                for group in reading_order.iterfind(f".//{{{self.ns}}}*"):
                    # Check if the group is an 'OrderedGroup'
                    if ET.QName(group.tag).localname == 'OrderedGroup':
                        # Find all 'RegionRefIndexed' elements and sort them by index
                        ro_ids += [ref.attrib['regionRef'] for ref in
                                  sorted(group.findall(f"./{{{self.ns}}}RegionRefIndexed"),
                                         key=lambda r: int(r.attrib['index']))]
        if mode == 'document' or (not ro_ids and mode == 'auto'):
            for region in self.root.findall(f".//{{{self.ns}}}*"):
                region_type = ET.QName(region.tag).localname
                if region_type in ['TableRegion', 'TextRegion']:
                    region_id = region.attrib.get('id', None)  # Get the ID attribute
                    if region_id:
                        ro_ids.append(region_id)
        # Return the collected text from regions
        return ro_ids

    def valid_region_id(self, id):
        region = self.root.find(f".//{{{self.ns}}}*[@id='r{id}']")
        return not region or ET.QName(region.tag).localname in ['TableRegion', 'TextRegion']

    def __reassign_id(self, element, ele, tag, id):
        for child in ele.iter(f"{{{self.ns}}}{tag}"):
            new_id = id+f"{element['id'].get(tag)}{element['counter'].get(element['id'].get(tag))}"
            child.set('id', new_id)
            element['counter'][element['id'].get(tag)] += 1
            if tag in element['order'].keys():
                self.__reassign_id(element, child, element['order'].get(tag), new_id)
        element['counter'][element['id'].get(tag)] = 1

    def reassign_ids(self, reading_order_mode):
        """
        Reassigning new IDs to TableRegion and TextRegion elements
        Args:
            reading_order_mode:

        Returns:

        """
        element = {'order': {'TableRegion': 'TableCell', 'TableCell': 'TextLine',
                         'TextRegion': 'TextLine', 'TextLine': 'Word', 'Word': 'Glyph'},
                   'id': {'TableRegion': 'r', 'TableCell': 'c',
                      'TextRegion': 'r', 'TextLine': 'l', 'Word': 'w', 'Glyph': 'g'},
                   'id_mapping': {}}
        element['counter'] = Counter(set(element.get('id').values()))

        region_ids = defaultdict(list)
        ro_ids = self.get_region_reading_order_ids(reading_order_mode)

        [region_ids.__setitem__(ro_id, []) for ro_id in ro_ids]
        [region_ids.__getitem__(region.attrib.get('id', len(region_ids.keys()))).append(region)
            for region in self.root.findall(f".//{{{self.ns}}}*")
            if ET.QName(region.tag).localname in ['TableRegion', 'TextRegion']]
        for id, regions in region_ids.items():
            while not self.valid_region_id(str(element['counter']['r'])):
                element['counter']['r'] += 1
            element['id_mapping'][id] = str(element['counter']['r'])
            for region in regions:
                region.set('id', f"r{element['counter']['r']}")
                self.__reassign_id(element, region, element['order'].get(ET.QName(region.tag).localname),
                           f"r{element['counter']['r']}")
            element['counter']['r'] += 1
        reading_order = self.tree.find(f".//{{{self.ns}}}ReadingOrder")
        if reading_order is not None:
            # Process each group in the reading order
            for group in reading_order.iterfind(f".//{{{self.ns}}}*"):
                for region_ref in group.iterfind(f".//{{{self.ns}}}RegionRefIndexed"):
                    region_idx = region_ref.attrib.get('regionRef')
                    region_ref.set('regionRef', element['id_mapping'].get(region_idx, region_idx))

    def counter(self, level: str = 'textlines') -> int:
        """
        Counts elements at different levels in the page.
        """
        if level in ['glyphs', 'words', 'textlines']:
            return sum([tr.counter(level=level) for tr in self.regions.textregions] +
                       [tc.counter(level=level) for tableregion in self.regions.tableregions \
                        for tc in tableregion.tablecells])

        if level == 'tablecells':
            return sum(len(tableregion.tablecells) for tableregion in self.regions.tableregions)

        if 'regions' in level:
            if 'table' in level:
                return len(self.regions.tableregions)
            if 'text' in level:
                return len(self.regions.textregions)
        return 0

    @staticmethod
    def _open_xml(filepath: Path = '') -> Tuple[ET.Element, ET._ElementTree, str]:
        """
        Opens a PAGE XML file and returns its tree, root, and namespace.
        """
        return parse_xml(filepath)

    def save_xml(self, filepath: Path) -> None:
        """
        Saves the modified XML object into a PAGE XML file.
        """
        write_xml(self, filepath)
        filepath.parent.mkdir(parents=True, exist_ok=True)
        self.tree.write(str(filepath.absolute()),
                        xml_declaration=True,
                        standalone=True,
                        encoding='utf-8')

    @staticmethod
    def dehyphe(lines: list) -> list:
        """
        Removes hyphens from OCR-ed lines stored in a list. Returns plain text.
        The hyphens are taken from the OCR-D guidelines for hyphenation:
        https://ocr-d.de/en/gt-guidelines/trans/trSilbentrennung.html.
        """
        hyphens = ['-', '-', '⹀', '⸗']
        if not lines:
            return []

        lines = [line.strip() for line in lines if line != '']
        dehyphenated_lines = []

        for i in range(len(lines)):
            current_line = lines[i]
            if i < len(lines) - 1 and current_line and current_line[-1] in hyphens:
                next_line = lines[i + 1]
                first_word_next_line = next_line.split(' ', 1)[0]
                if first_word_next_line:
                    if first_word_next_line[0].isupper():
                        dehyphenated_lines.append(current_line)
                    else:
                        dehyphenated_lines.append(current_line.rstrip(''.join(hyphens)) + first_word_next_line)
                    lines[i + 1] = next_line[len(first_word_next_line):].lstrip()
                else:
                    dehyphenated_lines.append(current_line)
            else:
                dehyphenated_lines.append(current_line)

        return dehyphenated_lines

    def extract_fulltext(self, level="textline", dehyphenate=False,
                         reading_order=True, reading_order_mode='reading_order', delimiter='\n') -> str:
        """
        Extracts the full text from the PAGE XML file.
        """
        fulltext = []
        if reading_order:
            for ro_ids in self.get_region_reading_order_ids():
                region = self.root.find(f'.//*[@id="{ro_ids}"]')
                fulltext = [unicode_ele.text for textline in region.iterfind(f".//{{{self.ns}}}TextLine")
                            for unicode_ele in textline.iterfind(f'.//{{{self.ns}}}Unicode') if unicode_ele.text]
        else:
            fulltext = [unicode_ele.text for textline in self.root.iterfind(f'.//{{{self.ns}}}TextLine')
                        for unicode_ele in textline.iterfind(f'.//{{{self.ns}}}Unicode') if unicode_ele.text]

        if dehyphenate and fulltext:
            fulltext = self.dehyphe(fulltext)

        return delimiter.join(fulltext)

    def page_coords(self, returntype: str = "string"):
        """
        Returns the coordinates of the page in various formats.
        """
        valid_returntypes = ["string", "tuples", "points", "polygon", "linearring"]
        if returntype not in valid_returntypes:
            return None

        coord_tuples = [(0, 0), (self.page_size()[0], 0), self.page_size(), (0, self.page_size()[1])]

        if returntype == "string":
            return " ".join(f"{x},{y}" for x, y in coord_tuples)
        if returntype == "tuples":
            return coord_tuples
        if returntype == "points":
            return MultiPoint(coord_tuples)
        if returntype == "polygon":
            return Polygon(coord_tuples)
        if returntype == "linearring":
            return LinearRing(coord_tuples)

    def page_size(self) -> tuple:
        """
        Returns the width and height of the page.
        """
        page_info = self.root.find(f"{{{self.ns}}}Page")
        return int(page_info.attrib['imageWidth']), int(page_info.attrib['imageHeight'])

    def page_filename(self) -> str:
        """
        Returns the filename of the page image.
        """
        page_info = self.root.find(f"{{{self.ns}}}Page")
        return page_info.attrib['imageFilename']

    def delete_element(self, element: ET._Element) -> None:
        """
        Deletes a given element from the PAGE XML.
        """
        element.getparent().remove(element)

    def delete_textlevel(self, level: str = "word") -> None:
        """
        Deletes elements at a specific text level ('word', 'line', or 'region') from the PAGE XML.
        """
        if level == 'word':
            self._delete_words()

        elif level == 'line':
            self._delete_lines()

        elif level == 'region':
            self._delete_regions()

    def _delete_words(self) -> None:
        """
        Deletes all 'Word' elements from the PAGE XML.
        """
        for word_element in self.root.iter(f"{{{self.ns}}}Word"):
            self.delete_element(word_element)

    def _delete_lines(self) -> None:
        """
        Deletes all 'TextEquiv' elements from 'TextLine' elements in the PAGE XML.
        """
        for region in self._iterate_regions():
            for textline in region.textlines:
                text_equiv = textline.xml_element.find(f"{{{self.ns}}}TextEquiv")
                if text_equiv is not None:
                    self.delete_element(text_equiv)

    def _delete_regions(self) -> None:
        """
        Deletes all 'TextEquiv' elements from 'TextRegion' elements in the PAGE XML.
        """
        for region in self._iterate_regions():
            text_equiv = region.xml_element.find(f"{{{self.ns}}}TextEquiv")
            if text_equiv is not None:
                self.delete_element(text_equiv)

    def _iterate_regions(self):
        """
        Generator to iterate through all regions in the page.
        """
        for regiontypes, regions in self.regions.__dict__.items():
            for region in regions:
                yield region
