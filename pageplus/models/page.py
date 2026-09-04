from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

import lxml.etree as ET
from shapely.geometry import LinearRing, MultiPoint, Polygon

from pageplus.io.parser import parse_xml
from pageplus.io.writer import write_xml
from pageplus.models.basic_elements import CoordElement, Region
from pageplus.models.table_elements import TableRegion
from pageplus.models.text_elements import TextRegion
from pageplus.models.metadata import Metadata
from pageplus.utils.constants import PcGtsVersion
from pageplus.utils.validation import validate_version_compatibility


from typing import Dict, Any


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
        self.load_regions()

    def compute_pseudobaselines(self, position: str = 'bottom', cut_to_polygon: bool = True) -> int:
        """
        Computes pseudo-baselines for all textlines across all text and table regions on the page.
        Returns the total number of textlines updated.
        """
        count = 0
        for region in (self.regions.textregions or []):
            for line in (region.textlines or []):
                try:
                    line.compute_pseudobaseline(position=position, cut_to_polygon=cut_to_polygon, update=True)
                    count += 1
                except Exception:
                    pass

        for tableregion in (self.regions.tableregions or []):
            for tc in (tableregion.tablecells or []):
                for line in (tc.textlines or []):
                    try:
                        line.compute_pseudobaseline(position=position, cut_to_polygon=cut_to_polygon, update=True)
                        count += 1
                    except Exception:
                        pass
        return count

    def update_pcgts_version(self, version: PcGtsVersion):
        """
        Updates the PcGts xmlns and schemaLocation to a specific version.
        Args:
            version (PcGtsVersion): The target PAGE XML version.
        """
        if self.root is None:
            return

        version_str = version.value
        
        if self.ns.rsplit('/', 1)[1] == version_str:
            print(f"Page already has the correct version: {version_str}")
            return

        new_ns = f"http://schema.primaresearch.org/PAGE/gts/pagecontent/{version_str}"
        new_schema_location = f"{new_ns} {new_ns}/pagecontent.xsd"

        # Create a new root element with the correct namespace
        new_root = ET.Element("PcGts", nsmap={None: new_ns, "xsi": "http://www.w3.org/2001/XMLSchema-instance"})
        
        # Copy all attributes from the old root, but update the namespace-related ones
        for attr_name, attr_value in self.root.attrib.items():
            if attr_name == "xmlns":
                # Skip the old xmlns, we'll set the new one via nsmap
                continue
            elif attr_name == "{http://www.w3.org/2001/XMLSchema-instance}schemaLocation":
                # Update schemaLocation
                new_root.set("{http://www.w3.org/2001/XMLSchema-instance}schemaLocation", new_schema_location)
            else:
                # Copy other attributes as-is
                new_root.set(attr_name, attr_value)
        
        # Set the schemaLocation if it wasn't already set
        if "{http://www.w3.org/2001/XMLSchema-instance}schemaLocation" not in new_root.attrib:
            new_root.set("{http://www.w3.org/2001/XMLSchema-instance}schemaLocation", new_schema_location)
        
        # Copy all children from the old root to the new one, updating their namespaces
        for child in self.root:
            self._copy_element_with_new_namespace(child, new_root, new_ns)
        
        # Replace the old root with the new one in the tree
        self.tree._setroot(new_root)
        self.root = new_root
        self.ns = new_ns

    def _copy_element_with_new_namespace(self, source_element, parent_element, new_ns):
        """
        Recursively copy an element and all its children, updating namespaces.
        """
        # Get the local name (without namespace prefix)
        local_name = ET.QName(source_element).localname
        
        # Create new element with the new namespace
        new_element = ET.SubElement(parent_element, f"{{{new_ns}}}{local_name}")
        
        # Copy attributes
        for attr_name, attr_value in source_element.attrib.items():
            new_element.set(attr_name, attr_value)
        
        # Copy text content
        if source_element.text:
            new_element.text = source_element.text
        
        # Copy tail content
        if source_element.tail:
            new_element.tail = source_element.tail
        
        # Recursively copy children
        for child in source_element:
            self._copy_element_with_new_namespace(child, new_element, new_ns)

    def validate_version_compatibility(self, version: PcGtsVersion) -> Dict[str, Any]:
        """
        Validates the compatibility of the PAGE XML version.
        """
        return validate_version_compatibility(self.root, version)

    def get_metadata(self) -> Metadata:
        """
        Gets the metadata of the PAGE XML file by reading its child elements.
        """
        metadata_element = self.root.find(f"{{{self.ns}}}Metadata")
        return Metadata.from_xml(metadata_element, self.ns)

    def set_metadata(self, metadata: Metadata = None, new: bool = False):
        """
        Sets the metadata of the PAGE XML file as child elements.
        If no metadata is provided, a default metadata is created.
        """
        if metadata is None:
            metadata = Metadata(
                creator="PagePlus",
                created=datetime.now(),
                last_change=datetime.now(),
                comments="")

        metadata_element = self.root.find(f"{{{self.ns}}}Metadata")
        if metadata_element is None:
            metadata_element = ET.SubElement(self.root, f"{{{self.ns}}}Metadata")

        metadata.update_xml_element(metadata_element, self.ns, new)

    def load_regions(self):
        text_region_xpath = f"{{{self.ns}}}TextRegion"
        self.regions.textregions = [
            TextRegion(
                ele,
                self.ns,
                parent=self) for ele in self.root.iter(text_region_xpath)]

        table_region_xpath = f"{{{self.ns}}}TableRegion"
        self.regions.tableregions = [
            TableRegion(
                ele,
                self.ns,
                parent=self) for ele in self.root.iter(table_region_xpath)]

    def get_region_reading_order_ids(
            self,
            mode: str = 'auto',
            region_types=('TableRegion,TextRegion')):
        ro_ids = []
        if mode in ['auto', 'reading_order']:
            reading_order = self.tree.find(f".//{{{self.ns}}}ReadingOrder")
            if reading_order is not None:
                # Process each group in the reading order
                for group in reading_order.iterfind(f".//{{{self.ns}}}*"):
                    # Check if the group is an 'OrderedGroup'
                    if ET.QName(group.tag).localname == 'OrderedGroup':
                        # Find all 'RegionRefIndexed' elements and sort them by
                        # index
                        ro_ids += [ref.attrib['regionRef'] for ref in
                                   sorted(group.findall(f"./{{{self.ns}}}RegionRefIndexed"),
                                          key=lambda r: int(r.attrib['index']))]
        if mode == 'document' or (not ro_ids and mode == 'auto'):
            for region in self.root.findall(f".//{{{self.ns}}}*"):
                region_type = ET.QName(region.tag).localname
                if region_type in region_types:
                    region_id = region.attrib.get(
                        'id', None)  # Get the ID attribute
                    if region_id:
                        ro_ids.append(region_id)
        # Return the collected text from regions
        return ro_ids

    def get_ordered_regions(
            self,
            mode: str = 'auto',
            region_types=('TableRegion,TextRegion')) -> List:
        ordered_regions = []
        for ro_ids in self.get_region_reading_order_ids(mode, region_types):
            region = self.root.find(f'.//*[@id="{ro_ids}"]')
            try:
                region_tag = ET.QName(region.tag).localname
            except BaseException:
                continue
            if region is not None and region_tag not in region_types:
                continue
            region = {
                'Region': Region,
                'TextRegion': TextRegion,
                'TableRegion': TableRegion}.get(
                region_tag,
                Region)(
                region,
                self.ns,
                region.getparent())
            ordered_regions.append(region)
        return ordered_regions

    def get_region_by_id(self, id) -> Region:
        for region in self.regions.textregions + self.regions.tableregions:
            if region.get_id() == id:
                return region
        return None

    def valid_region_id(self, id):
        region = self.root.find(f".//{{{self.ns}}}*[@id='r{id}']")
        return not region or ET.QName(region.tag).localname in [
            'TableRegion', 'TextRegion']

    def __reassign_id(self, element, ele, tag, id):
        for child in ele.iter(f"{{{self.ns}}}{tag}"):
            new_id = id + \
                f"{element['id'].get(tag)}{element['counter'].get(element['id'].get(tag))}"
            child.set('id', new_id)
            element['counter'][element['id'].get(tag)] += 1
            if tag in element['order'].keys():
                self.__reassign_id(
                    element, child, element['order'].get(tag), new_id)
        element['counter'][element['id'].get(tag)] = 1

    def reassign_ids(self, reading_order_mode):
        """
        Reassigning new IDs to TableRegion and TextRegion elements
        Args:
            reading_order_mode:

        Returns:

        """
        element = {
            'order': {
                'TableRegion': 'TableCell',
                'TableCell': 'TextLine',
                'TextRegion': 'TextLine',
                'TextLine': 'Word',
                'Word': 'Glyph'},
            'id': {
                'TableRegion': 'r',
                'TableCell': 'c',
                'TextRegion': 'r',
                'TextLine': 'l',
                'Word': 'w',
                'Glyph': 'g'},
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
                self.__reassign_id(
                    element, region, element['order'].get(
                        ET.QName(region.tag).localname), f"r{element['counter']['r']}")
            element['counter']['r'] += 1
        reading_order = self.tree.find(f".//{{{self.ns}}}ReadingOrder")
        if reading_order is not None:
            # Process each group in the reading order
            for group in reading_order.iterfind(f".//{{{self.ns}}}*"):
                for region_ref in group.iterfind(
                        f".//{{{self.ns}}}RegionRefIndexed"):
                    region_idx = region_ref.attrib.get('regionRef')
                    region_ref.set(
                        'regionRef', element['id_mapping'].get(
                            region_idx, region_idx))

    def counter(self, level: str = 'textlines') -> int:
        """
        Counts elements at different levels in the page.
        """
        if level in ['glyphs', 'words', 'textlines']:
            return sum([tr.counter(level=level) for tr in self.regions.textregions] +
                       [tc.counter(level=level) for tableregion in self.regions.tableregions
                        for tc in tableregion.tablecells])

        if level == 'tablecells':
            return sum(len(tableregion.tablecells)
                       for tableregion in self.regions.tableregions)

        if 'regions' in level:
            if 'table' in level:
                return len(self.regions.tableregions)
            if 'text' in level:
                return len(self.regions.textregions)
        return 0

    @staticmethod
    def _open_xml(
            filepath: Path = '') -> Tuple[ET.Element, ET._ElementTree, str]:
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
                        pretty_print=True,
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
            if i < len(lines) - \
                    1 and current_line and current_line[-1] in hyphens:
                next_line = lines[i + 1]
                first_word_next_line = next_line.split(' ', 1)[0]
                if first_word_next_line:
                    if first_word_next_line[0].isupper():
                        dehyphenated_lines.append(current_line)
                    else:
                        dehyphenated_lines.append(current_line.rstrip(
                            ''.join(hyphens)) + first_word_next_line)
                    lines[i +
                          1] = next_line[len(first_word_next_line):].lstrip()
                else:
                    dehyphenated_lines.append(current_line)
            else:
                dehyphenated_lines.append(current_line)

        return dehyphenated_lines

    def extract_fulltext(
            self,
            level="textline",
            dehyphenate=False,
            reading_order=True,
            reading_order_mode='reading_order',
            delimiter='\n') -> str:
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

    def get_id(self):
        if "pcGtsId" in self.root.attrib:
            return self.root.attrib["pcGtsId"]

    def get_coordinates(self, returntype: str = "string"):
        return self.page_coords(returntype)

    def get_tags(
            self,
            levels: list[str] = [
                'Word',
                'TableRegion',
                'Textline',
                'TextRegion'],
            details: bool = False):
        """
        Get all tags for a specific level ('Word', 'TableRegion', 'Textline', or 'TextRegion') from the PAGE XML.
        """
        from collections import defaultdict
        tag_counts = defaultdict(lambda: defaultdict(int))

        for region in self.regions.textregions + self.regions.tableregions:
            region_name = region.__class__.__name__
            if region_name in levels:
                tag = region.get_tag()
                tag_counts[tag][region_name] += 1

            if 'Textline' in levels:
                for line in region.textlines:
                    tag = line.get_tag()
                    tag_counts[tag]['Textline'] += 1

        return tag_counts.keys() if not details else dict(tag_counts)

    def page_coords(self, returntype: str = "string", buffer: int = 0):
        """
        Returns the coordinates of the page in various formats.
        """
        valid_returntypes = [
            "string",
            "tuples",
            "points",
            "polygon",
            "linearring"]
        if returntype not in valid_returntypes:
            return None

        coord_tuples = [
            (-buffer, -buffer), 
            (self.page_size()[0]+buffer, -buffer),
            (self.page_size()[0]+buffer, self.page_size()[1]+buffer),
            (-buffer, self.page_size()[1]+buffer)
        ]
        
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
        return int(
            page_info.attrib['imageWidth']), int(
            page_info.attrib['imageHeight'])

    def print_space(self):
        """
        Returns the print space coords as string.
        """
        print_space = self.root.find(f".//{{{self.ns}}}PrintSpace")
        if print_space is not None:
            return CoordElement(print_space, self.ns, None)

    def border(self):
        """
        Returns the print space coords as string.
        """
        border = self.root.find(f".//{{{self.ns}}}Border")
        if border is not None:
            return CoordElement(border, self.ns, None)

    def imageFilename(self) -> str:
        """
        Returns the width and height of the page.
        """
        page_info = self.root.find(f"{{{self.ns}}}Page")
        return page_info.attrib['imageFilename']

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

    def add_element(self, element: ET._Element) -> None:
        """
        Adds a given element to the PAGE XML.
        """
        element.getparent().addnext(element)

    def delete_textlevel(self, level: str = "Word") -> None:
        """
        Deletes elements at a specific text level ('Word', 'TableRegion', 'Textline', or 'TextRegion') from the PAGE XML.
        """
        if level == 'Word':
            count = self._delete_words()
            print(f"Deleted {count} Words.")

        elif level == 'Textline':
            count = self._delete_text(
                [
                    line for region in self.regions.textregions +
                    self.regions.tableregions for line in region.textlines])
            print(f"Deleted {count} TextLines")

        elif level == 'TextRegion':
            count = self._delete_text(self.regions.textregions)
            print(f"Deleted {count} TextRegions")

        elif level == 'TableRegion':
            count = self._delete_text(self.regions.tableregions)
            print(f"Deleted {count} TableRegions")

    def _delete_words(self) -> None:
        """
        Deletes all 'Word' elements from the PAGE XML.
        """
        count = 0
        for word_element in self.root.iter(f"{{{self.ns}}}Word"):
            self.delete_element(word_element)
            count += 1
        return count

    def _delete_text(self, elements: list) -> None:
        """
        Deletes all 'TextEquiv' elements from 'TextLine' elements in the PAGE XML.
        """
        count = 0
        for element in elements:
            text_equiv = element.xml_element.find(f"{{{self.ns}}}TextEquiv")
            if text_equiv is not None:
                self.delete_element(text_equiv)
                count += 1
        return count

    def _iterate_regions(self):
        """
        Generator to iterate through all regions in the page.
        """
        for regiontype, regions in self.regions.__dict__.items():
            for region in regions:
                yield region

    def delete_fill_characters(
        self,
        levels: Any = ("TableRegion",),
        fill_character: str = ".",
        min_count: int = 2,
    ) -> int:
        """
        Strips multiple trailing fill characters at the end of text lines within specified levels.

        Args:
            levels: Granularity levels ('TableRegion', 'TextRegion', 'Textline').
            fill_character: Fill character to strip when occurring at least `min_count` times at line end (default: '.').
            min_count: Minimum count of fill character occurrences at line end to trigger deletion (default: 2).

        Returns:
            Number of text elements modified.
        """
        import re
        if not fill_character:
            return 0

        # Normalize levels
        if not isinstance(levels, (list, tuple, set)):
            levels = [levels]

        level_names = set()
        for lvl in levels:
            if hasattr(lvl, "name"):
                level_names.add(lvl.name)
            elif hasattr(lvl, "value"):
                level_names.add(str(lvl.value))
            elif isinstance(lvl, str):
                level_names.add(lvl)

        escaped_char = re.escape(fill_character)
        pattern = re.compile(rf'(?:\s*{escaped_char}){{{min_count},}}\s*$')

        count = 0

        def _clean_textline(tl) -> bool:
            curr_text = tl.get_text()
            if curr_text and pattern.search(curr_text):
                cleaned = pattern.sub('', curr_text).rstrip()
                tl.update_text(cleaned)
                return True
            return False

        def _clean_element_unicode(xml_elem) -> bool:
            mod = False
            for uni in xml_elem.findall(f".//{{{self.ns}}}Unicode"):
                if uni.text and pattern.search(uni.text):
                    uni.text = pattern.sub('', uni.text).rstrip()
                    mod = True
            if not mod:
                for uni in xml_elem.findall(".//{*}Unicode"):
                    if uni.text and pattern.search(uni.text):
                        uni.text = pattern.sub('', uni.text).rstrip()
                        mod = True
            return mod

        if "Textline" in level_names:
            for tr in (self.regions.textregions or []):
                for tl in (tr.textlines or []):
                    if _clean_textline(tl):
                        count += 1
            for tableregion in (self.regions.tableregions or []):
                for tc in (tableregion.tablecells or []):
                    for tl in (tc.textlines or []):
                        if _clean_textline(tl):
                            count += 1
        else:
            if "TextRegion" in level_names:
                for tr in (self.regions.textregions or []):
                    if tr.textlines:
                        for tl in tr.textlines:
                            if _clean_textline(tl):
                                count += 1
                    else:
                        if _clean_element_unicode(tr.xml_element):
                            count += 1

            if "TableRegion" in level_names:
                for tableregion in (self.regions.tableregions or []):
                    for tc in (tableregion.tablecells or []):
                        if tc.textlines:
                            for tl in tc.textlines:
                                if _clean_textline(tl):
                                    count += 1
                        else:
                            if _clean_element_unicode(tc.xml_element):
                                count += 1

        return count

    def apply_text_mapping(
        self,
        handler: Any = None,
        mapping_profile: str = "GT4Hist",
        textnormalization: str = "NFC",
        mode: str = "deterministic",
        filename: Optional[str] = None
    ) -> Tuple[bool, int, dict]:
        """
        Applies a guideline/profile mapping to all textlines (and text elements) in the page.

        Args:
            handler: Optional pre-configured Mappinghandler instance.
            mapping_profile: Mapping profile name if handler is not provided.
            textnormalization: Unicode normalization ('NFC', 'NFD', 'NFKC', 'NFKD', or 'None').
            mode: Mapping mode from profile (default: 'deterministic').
            filename: Name of the file being processed for logging/stats.

        Returns:
            Tuple of (is_modified: bool, modified_count: int, change_log: dict)
        """
        import unicodedata
        from pageplus.utils.guidelines.lib.processhandler import Mappinghandler

        fname = filename
        if not fname:
            if hasattr(self, 'filename') and self.filename:
                fname = Path(self.filename).name
            else:
                fname = self.page_filename() or "page.xml"

        if handler is None:
            handler = Mappinghandler(
                fnames=[str(self.filename)] if (hasattr(self, 'filename') and self.filename) else [],
                guideline=mapping_profile,
                textnormalization=textnormalization
            )
        count = 0
        change_log = {}

        def _process_line(line) -> bool:
            orig = line.get_text()
            if not orig:
                return False
            norm_text = orig
            if textnormalization and textnormalization.lower() != "none":
                norm_text = unicodedata.normalize(textnormalization, orig)
            mapped_text = handler.mapping_by_guideline(
                norm_text, line.get_id(), fname, mode=mode
            )
            if orig != mapped_text:
                line.update_text(mapped_text)
                change_log[line.get_id()] = {
                    'original': orig,
                    'new': mapped_text
                }
                return True
            return False

        # Process TextRegions
        for region in (self.regions.textregions or []):
            for line in (region.textlines or []):
                if _process_line(line):
                    count += 1

        # Process TableRegions
        for tableregion in (self.regions.tableregions or []):
            for cell in (tableregion.tablecells or []):
                for line in (cell.textlines or []):
                    if _process_line(line):
                        count += 1

        return count > 0, count, change_log

    def _update_reading_order_xml(self, ordered_regions: List[Any]) -> None:
        """
        Updates or creates the <ReadingOrder> element in the PAGE XML
        and synchronizes custom="readingOrder {index:X;}" attributes on regions and textlines.
        """
        if not ordered_regions:
            return

        ro_elem = self.tree.find(f".//{{{self.ns}}}ReadingOrder")
        if ro_elem is None:
            page_elem = self.root.find(f".//{{{self.ns}}}Page")
            target = page_elem if page_elem is not None else self.root
            ro_elem = ET.Element(f"{{{self.ns}}}ReadingOrder")
            target.insert(0, ro_elem)
        else:
            ro_elem.clear()

        import time
        import re
        group_id = f"ro_{int(time.time())}"
        ordered_group = ET.SubElement(ro_elem, f"{{{self.ns}}}OrderedGroup", attrib={
            "id": group_id,
            "caption": "Regions reading order"
        })

        for idx, item in enumerate(ordered_regions):
            if hasattr(item, "get_id"):
                rid = item.get_id() or item.xml_element.get("id")
                region_obj = item
                elem = item.xml_element if hasattr(item, "xml_element") else None
            elif isinstance(item, str):
                rid = item
                region_obj = self.get_region_by_id(rid)
                elem = region_obj.xml_element if region_obj and hasattr(region_obj, "xml_element") else self.root.find(f'.//*[@id="{rid}"]')
            else:
                rid = getattr(item, "id", str(item))
                region_obj = getattr(item, "tr", None)
                elem = getattr(region_obj, "xml_element", None)

            ET.SubElement(ordered_group, f"{{{self.ns}}}RegionRefIndexed", attrib={
                "index": str(idx),
                "regionRef": str(rid)
            })

            # Synchronize custom attribute on the region XML element
            if elem is not None:
                custom = elem.get("custom")
                if custom is not None:
                    if re.search(r'readingOrder\s*\{[^}]*\}', custom):
                        new_custom = re.sub(
                            r'readingOrder\s*\{[^}]*\}',
                            f'readingOrder {{index:{idx};}}',
                            custom
                        )
                        elem.set("custom", new_custom)
                    else:
                        elem.set("custom", f"readingOrder {{index:{idx};}} {custom}".strip())

                # Also synchronize textline reading order within region
                if region_obj is not None and hasattr(region_obj, "textlines") and region_obj.textlines:
                    for l_idx, line in enumerate(region_obj.textlines):
                        if hasattr(line, "xml_element") and line.xml_element is not None:
                            l_custom = line.xml_element.get("custom")
                            if l_custom is not None and re.search(r'readingOrder\s*\{[^}]*\}', l_custom):
                                new_l_custom = re.sub(
                                    r'readingOrder\s*\{[^}]*\}',
                                    f'readingOrder {{index:{l_idx};}}',
                                    l_custom
                                )
                                line.xml_element.set("custom", new_l_custom)

    def update_reading_order_indices(
        self,
        reorder_dom: bool = True,
        sort_lines: bool = False
    ) -> int:
        """
        Updates the custom="readingOrder {index:X;}" attributes on all regions and textlines
        according to the <ReadingOrder> element in the PAGE XML.

        If <ReadingOrder> exists, extracts regionRefs and assigns their index to each region's custom attribute.
        If reorder_dom is True, also physically reorders the XML elements in the DOM to match the reading order.

        Returns:
            Number of regions updated.
        """
        ro_ids = self.get_region_reading_order_ids(mode='reading_order')
        if not ro_ids:
            ro_ids = self.get_region_reading_order_ids(mode='document')

        if not ro_ids:
            return 0

        import re
        updated_count = 0
        ordered_regions = []

        for idx, rid in enumerate(ro_ids):
            region_obj = self.get_region_by_id(rid)
            elem = region_obj.xml_element if region_obj and hasattr(region_obj, "xml_element") else self.root.find(f'.//*[@id="{rid}"]')
            if elem is not None:
                custom = elem.get("custom")
                if custom is not None:
                    if re.search(r'readingOrder\s*\{[^}]*\}', custom):
                        new_custom = re.sub(
                            r'readingOrder\s*\{[^}]*\}',
                            f'readingOrder {{index:{idx};}}',
                            custom
                        )
                        elem.set("custom", new_custom)
                    else:
                        elem.set("custom", f"readingOrder {{index:{idx};}} {custom}".strip())
                else:
                    elem.set("custom", f"readingOrder {{index:{idx};}}")

                if region_obj is not None:
                    ordered_regions.append(region_obj)
                    if sort_lines and hasattr(region_obj, "sort_baselines"):
                        try:
                            region_obj.sort_baselines(mode='single_col')
                        except Exception:
                            try:
                                region_obj.sort_lines()
                            except Exception:
                                pass

                    if hasattr(region_obj, "textlines") and region_obj.textlines:
                        for l_idx, line in enumerate(region_obj.textlines):
                            if hasattr(line, "xml_element") and line.xml_element is not None:
                                l_custom = line.xml_element.get("custom")
                                if l_custom is not None and re.search(r'readingOrder\s*\{[^}]*\}', l_custom):
                                    new_l_custom = re.sub(
                                        r'readingOrder\s*\{[^}]*\}',
                                        f'readingOrder {{index:{l_idx};}}',
                                        l_custom
                                    )
                                    line.xml_element.set("custom", new_l_custom)

                updated_count += 1

        if reorder_dom and ordered_regions:
            for r in ordered_regions:
                elem = r.xml_element
                parent = elem.getparent()
                if parent is not None:
                    parent.remove(elem)
                    parent.append(elem)

            self.regions.textregions = [r for r in ordered_regions if isinstance(r, TextRegion)]

        self._update_reading_order_xml(ordered_regions if ordered_regions else ro_ids)

        return updated_count

    def sort_two_column(
        self,
        based_on_baselines: bool = False,
        update_reading_order: bool = True,
        gap_threshold: Optional[float] = None,
        center_tolerance: float = 0.15,
        span_width_ratio: float = 0.6,
        sort_lines_internally: bool = True,
    ) -> List[Any]:
        """
        Two-Column Sorting Algorithm for newspapers and periodicals.

        Sorting flow:
          1. Header and top page numbers (read first, top-to-bottom).
          2. Body sections divided by centered/spanning headings ('Next Topic') or large vertical gaps:
             - Within each section: Left column paragraphs top-to-bottom, then Right column paragraphs top-to-bottom.
             - Spanning/centered heading (if any) placed immediately after its preceding section and before the next section.
          3. Footer, bottom page numbers, and signature marks (read last, top-to-bottom).

        Physically reorders the XML elements in the Page XML, updates self.regions.textregions,
        and optionally updates the <ReadingOrder> element.

        Returns:
            List of TextRegion objects in sorted order.
        """
        regions = list(self.regions.textregions or [])
        if not regions:
            return []

        page_w, page_h = self.page_size()

        class RegionInfo:
            def __init__(self, tr):
                self.tr = tr
                self.id = tr.get_id() or tr.xml_element.get('id')
                coords = tr.get_coordinates(returntype="tuple")
                if coords:
                    xs = [p[0] for p in coords]
                    ys = [p[1] for p in coords]
                    self.xmin, self.ymin, self.xmax, self.ymax = min(xs), min(ys), max(xs), max(ys)
                else:
                    w, h = tr.get_width_height(method="mrr")
                    c = tr.get_coordinates("polygon").centroid
                    self.xmin, self.ymin, self.xmax, self.ymax = c.x - w / 2, c.y - h / 2, c.x + w / 2, c.y + h / 2

                self.w = max(1.0, self.xmax - self.xmin)
                self.h = max(1.0, self.ymax - self.ymin)

                if based_on_baselines:
                    c = tr.get_mean_textline_centroid()
                    self.cx = float(c.x) if hasattr(c, 'x') else (self.xmin + self.xmax) / 2.0
                    self.cy = float(c.y) if hasattr(c, 'y') else (self.ymin + self.ymax) / 2.0
                else:
                    self.cx = (self.xmin + self.xmax) / 2.0
                    self.cy = (self.ymin + self.ymax) / 2.0

                elem_type = (tr.xml_element.get('type') or '').lower()
                custom_tag = (tr.get_tag() or '').lower()
                self.type = elem_type or custom_tag or 'paragraph'

        reg_infos = [RegionInfo(tr) for tr in regions]

        if not page_w or not page_h or page_w <= 0 or page_h <= 0:
            page_w = max(r.xmax for r in reg_infos) + 50
            page_h = max(r.ymax for r in reg_infos) + 50

        x_mid = page_w / 2.0

        header_group: List[RegionInfo] = []
        footer_group: List[RegionInfo] = []
        body_candidates: List[RegionInfo] = []

        for r in reg_infos:
            is_hdr = False
            is_ftr = False

            # Check header (running header / top page number)
            if r.type in ['header', 'running-header', 'page-header', 'head'] and r.ymin < 0.15 * page_h:
                is_hdr = True
            elif r.type in ['page-number', 'page_number', 'page-nr'] and r.ymin < 0.30 * page_h:
                is_hdr = True
            elif r.ymin < 0.05 * page_h and r.h < 0.05 * page_h and r.type not in ['paragraph']:
                is_hdr = True

            # Check footer
            if not is_hdr:
                if r.type in ['footer', 'signature-mark', 'catch-word', 'bottom-line']:
                    is_ftr = True
                elif r.type in ['page-number', 'page_number', 'page-nr'] and r.ymax > 0.65 * page_h:
                    is_ftr = True
                elif r.ymax > 0.92 * page_h and r.h < 0.08 * page_h:
                    is_ftr = True

            if is_hdr:
                header_group.append(r)
            elif is_ftr:
                footer_group.append(r)
            else:
                body_candidates.append(r)

        header_group.sort(key=lambda r: (r.ymin, r.xmin))
        footer_group.sort(key=lambda r: (r.ymin, r.xmin))

        def is_middle_region(r: RegionInfo) -> bool:
            if r.w >= span_width_ratio * page_w:
                return True
            # Crosses central divider significantly into both columns
            crosses_divider = (r.xmin <= x_mid - 0.05 * page_w) and (r.xmax >= x_mid + 0.05 * page_w)
            if crosses_divider:
                return True
            is_centered = abs(r.cx - x_mid) <= (center_tolerance * page_w)
            if is_centered and (r.xmin < x_mid and r.xmax > x_mid) and r.w >= 0.20 * page_w:
                return True
            if r.type in ['heading', 'subheading', 'title', 'headline', 'centered', 'caption']:
                if (r.xmin < x_mid < r.xmax) or (is_centered and r.w >= 0.15 * page_w and r.xmin < x_mid + 0.05 * page_w and r.xmax > x_mid - 0.05 * page_w):
                    return True
            return False

        # Refine x_mid based on left and right column candidates
        col_cands = [r for r in body_candidates if not is_middle_region(r)]
        if col_cands:
            left_cands = [r.cx for r in col_cands if r.cx < x_mid]
            right_cands = [r.cx for r in col_cands if r.cx >= x_mid]
            if left_cands and right_cands:
                from statistics import median
                x_mid = (median(left_cands) + median(right_cands)) / 2.0

        middle_regs = [r for r in body_candidates if is_middle_region(r)]
        middle_regs.sort(key=lambda r: (r.ymin, r.xmin))

        middle_blocks: List[List[RegionInfo]] = []
        for mr in middle_regs:
            if not middle_blocks:
                middle_blocks.append([mr])
            else:
                last_block = middle_blocks[-1]
                last_max_y = max(r.ymax for r in last_block)
                # Check for any column region that overlaps or starts between last_block and mr
                intervening = [
                    cr for cr in body_candidates
                    if not is_middle_region(cr) and (cr.ymin < mr.ymin and cr.ymax > last_max_y)
                ]
                gap = mr.ymin - last_max_y
                max_block_gap = max(80, 0.05 * page_h)
                if not intervening and gap <= max_block_gap:
                    last_block.append(mr)
                else:
                    middle_blocks.append([mr])

        gap_boundaries: List[float] = []
        if gap_threshold is not None and gap_threshold > 0:
            non_spanning = [r for r in body_candidates if not is_middle_region(r)]
            if non_spanning:
                sorted_by_y = sorted(non_spanning, key=lambda r: r.ymin)
                for i in range(len(sorted_by_y) - 1):
                    current_max_y = max(r.ymax for r in sorted_by_y[:i + 1])
                    next_min_y = min(r.ymin for r in sorted_by_y[i + 1:])
                    if next_min_y - current_max_y >= gap_threshold:
                        gap_mid = (current_max_y + next_min_y) / 2.0
                        gap_boundaries.append(gap_mid)

        dividers = []
        for mb in middle_blocks:
            min_y = min(r.ymin for r in mb)
            max_y = max(r.ymax for r in mb)
            dividers.append(('block', min_y, max_y, mb))
        for gb in gap_boundaries:
            dividers.append(('gap', gb, gb, None))
        dividers.sort(key=lambda d: d[1])

        ordered_body_regions: List[RegionInfo] = []
        remaining_columns = [r for r in body_candidates if not is_middle_region(r)]

        for div_type, div_min_y, div_max_y, div_obj in dividers:
            col_before = [
                r for r in remaining_columns
                if r.ymin < div_min_y - 5 or (r.ymin < div_max_y and r.cy < div_max_y)
            ]
            remaining_columns = [r for r in remaining_columns if r not in col_before]

            if col_before:
                left_col = [r for r in col_before if r.cx < x_mid]
                right_col = [r for r in col_before if r.cx >= x_mid]
                left_col.sort(key=lambda r: (r.ymin, r.xmin))
                right_col.sort(key=lambda r: (r.ymin, r.xmin))
                ordered_body_regions.extend(left_col)
                ordered_body_regions.extend(right_col)

            if div_type == 'block' and div_obj:
                sorted_mb = sorted(div_obj, key=lambda r: (r.ymin, r.xmin))
                ordered_body_regions.extend(sorted_mb)

        if remaining_columns:
            left_col = [r for r in remaining_columns if r.cx < x_mid]
            right_col = [r for r in remaining_columns if r.cx >= x_mid]
            left_col.sort(key=lambda r: (r.ymin, r.xmin))
            right_col.sort(key=lambda r: (r.ymin, r.xmin))
            ordered_body_regions.extend(left_col)
            ordered_body_regions.extend(right_col)

        full_info_order = header_group + ordered_body_regions + footer_group
        final_textregions = [info.tr for info in full_info_order]

        if sort_lines_internally:
            for tr in final_textregions:
                try:
                    tr.sort_baselines(mode='single_col')
                except Exception:
                    try:
                        tr.sort_lines()
                    except Exception:
                        pass

        for tr in final_textregions:
            elem = tr.xml_element
            parent = elem.getparent()
            if parent is not None:
                parent.remove(elem)
                parent.append(elem)

        self.regions.textregions = final_textregions

        if update_reading_order:
            self._update_reading_order_xml(final_textregions)

        return final_textregions

    def to_mistral_ocr(self, page_index: int = 0, extract_page_only: bool = False, **kwargs) -> Dict[str, Any]:
        """
        Converts the Page to Mistral Document OCR response JSON format.
        """
        from pageplus.utils.mappings.mistral_ocr import page_to_mistral_ocr
        return page_to_mistral_ocr(self, page_index=page_index, extract_page_only=extract_page_only, **kwargs)

