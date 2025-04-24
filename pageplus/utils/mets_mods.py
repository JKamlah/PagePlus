import re
from io import BytesIO
from pathlib import Path
from typing import Optional, List

import requests
import typer
from lxml import etree
from lxml.etree import Element, tostring

from pageplus.utils.exceptions import NotValidMetsException, MetsError
from pageplus.utils.constants import MIME_IMAGE_EXTENSIONS

# Define METS namespaces.
NSMAP = {
    'mets': 'http://www.loc.gov/METS/',
    'xsi': 'http://www.w3.org/2001/XMLSchema-instance',
    'xlink': 'http://www.w3.org/1999/xlink',
    'mods': 'http://www.loc.gov/mods/v3',
    'dv': 'http://dfg-viewer.de/',
    'vlz': 'http://vlz.namespace.uri',
    'premis': "info:lc/xmlns/premis-v2",
    'mix': "http://www.loc.gov/mix/v10",
    'vl': 'http://example.com/some/namespace'
}
XSI = "{%s}" % NSMAP['xsi']
XLINK = "{%s}" % NSMAP['xlink']
FALLBACK_NAMESPACE = "http://example.com/some/namespace"


def validate_mets(ctx: typer.Context, param: typer.CallbackParam, value: str):
    """ Validate xml """
    if value.endswith('.xml') and Path(value).exists():
        return value
    raise NotValidMetsException


def fix_missing_namespaces(xml_bytes: bytes) -> bytes:
    parser = etree.XMLParser(recover=True)
    tree = etree.fromstring(xml_bytes, parser=parser)

    for prefix, uri in NSMAP.items():
        if not tree.nsmap.get(prefix):
            pass
            # tree.set(f"xmlns:{prefix}", uri)

    return etree.tostring(tree, encoding='utf-8', xml_declaration=True)


def repair_namespace(mets: str):
    """
    Repair the namespace of the mets
    """

    # Define default known namespaces
    with open(mets, "r", encoding="utf-8") as f:
        content = f.read()

    def process_mets_block(match):
        original_opening_tag = match.group(1)
        inner_content = match.group(2)

        # Collect all prefixes used in the block
        used_prefixes = set(re.findall(r'</?([a-zA-Z_][\w\-]*):[a-zA-Z_][\w\-]*', inner_content))

        # Check if xsi or xlink is used in attributes (like xsi:type or xlink:href)
        if re.search(r'\bxsi:', inner_content):
            used_prefixes.add("xsi")
        if re.search(r'\bmods:', inner_content):
            used_prefixes.add("mods")
        if re.search(r'\bxlink:', inner_content):
            used_prefixes.add("xlink")


        # Parse existing xmlns declarations
        existing_decls = dict(re.findall(r'xmlns:([a-zA-Z0-9_]+)="([^"]+)"', original_opening_tag))
        # Add missing declarations
        for prefix in used_prefixes:
            if prefix not in existing_decls:
                existing_decls[prefix] = NSMAP.get(prefix, FALLBACK_NAMESPACE)

        # Build new opening tag with <mets:mets>
        new_tag = "<mets:mets"
        for k, v in sorted(existing_decls.items()):
            new_tag += f' xmlns:{k}="{v}"'

        # Add xsi:schemaLocation if xsi is used
        if "xsi" in existing_decls:
            new_tag += (
                ' xsi:schemaLocation="'
                'info:lc/xmlns/premis-v2 http://www.loc.gov/standards/premis/v2/premis-v2-0.xsd '
                'http://www.loc.gov/mods/v3 http://www.loc.gov/standards/mods/mods.xsd '
                'http://www.loc.gov/METS/ http://www.loc.gov/standards/mets/mets.xsd '
                'http://www.loc.gov/mix/v10 http://www.loc.gov/standards/mix/mix10/mix10.xsd"'
            )

        new_tag += ">"
        return f"{new_tag}{inner_content}</mets:mets>"

    # Replace all mets:mets blocks
    updated_content = re.sub(
        r"(<mets:mets[^>]*>)(.*?)(</mets:mets>)",
        lambda m: process_mets_block(m),
        content,
        flags=re.DOTALL
    )

    # Write output back
    with open(mets, "w", encoding="utf-8") as f:
        f.write(updated_content)

    return mets


def build_xml_tree(mets_obj, nsmap=None):
    """
    Recursively build an lxml Element tree from a MetsElement object.

    Special handling: If the parent tag is 'xmlData', children are appended directly.
    """
    nsmap = nsmap or NSMAP
    elem = Element(mets_obj.tag, nsmap=nsmap)
    for key, value in mets_obj.attributes.items():
        if value is not None:
            elem.set(key, str(value))
    if mets_obj.content:
        elem.text = mets_obj.content
    for child in mets_obj.children:
        if mets_obj.tag == "xmlData":
            elem.append(child)
        else:
            elem.append(build_xml_tree(child, nsmap))
    return elem


class MetsElement:
    """
    Base class for all METS elements.

    :param attributes: Dictionary of allowed attribute values.
    :param content: Textual content (if allowed).
    """
    tag: str = None
    allowed_attributes: dict = {}
    allowed_children: list = []
    allows_content: bool = False
    loose: bool = False
    verbose: bool = False

    def __init__(self, *, attributes: dict = None, content: str = None, loose: bool = True, verbose: bool = False):
        self.loose = loose
        self.verbose = verbose
        self.attributes = self.allowed_attributes.copy()
        if attributes:
            for key, value in attributes.items():
                if key in self.attributes:
                    self.attributes[key] = value
                else:
                    if not loose:
                        MetsError(f"WARNING: Attribute '{key}' is not allowed in element '{self.tag}'.")
                    if self.verbose:
                        print(f"WARNING: Attribute '{key}' is not allowed in element '{self.tag}'.")
                    self.attributes[key] = value

        if content is not None:
            if not self.allows_content and not loose:
                raise MetsError(f"Element '{self.tag}' does not allow content.")
            if not self.allows_content and self.verbose:
                print(MetsError(f"WARNING: Element '{self.tag}' does not allow content."))
            self.content = content
        else:
            self.content = None
        self.children = []

    def add_child(self, child: "MetsElement"):
        """Add a child element if its tag is allowed."""
        if child.tag in self.allowed_children:
            self.children.append(child)
        else:
            if self.loose:
                if self.verbose:
                    print(MetsError(f"WARNING: Child element '{child.tag}' not allowed in parent '{self.tag}'."))
                self.children.append(child)
            else:
                raise MetsError(f"WARNING: Child element '{child.tag}' not allowed in parent '{self.tag}'.")


    def remove_child(self, child: "MetsElement"):
        """Remove a child element."""
        self.children = [c for c in self.children if c != child]

    def get_children(self, tag: str):
        """Return a list of child elements that match the given tag."""
        return [c for c in self.children if c.tag == tag]

    def to_xml(self, nsmap=None) -> bytes:
        """Generate the complete XML document as bytes (including XML declaration)."""
        nsmap = nsmap or NSMAP
        root = build_xml_tree(self, nsmap)
        return b'<?xml version="1.0" encoding="UTF-8"?>\n' + tostring(root, encoding='UTF-8', pretty_print=True)


# --- METS - MODS Element Classes --- #

METS_MODS_DISPATCH = {}
def dispatch():
    def wrapper(cls): METS_MODS_DISPATCH[cls.tag] = cls; return cls
    return wrapper

@dispatch()
class Mets(MetsElement):
    tag = "mets"
    allowed_attributes = {
        "TYPE": None,
        "OBJID": None,
        "LABEL": None,
        "PROFILE": None,
        XSI + "schemaLocation": None
    }
    allowed_children = ["metsHdr", "dmdSec", "amdSec", "fileSec", "structMap", "behaviorSec", "structLink", "mets"]

    def save(self, filename: str, nsmap=None):
        """Save the generated XML document to a file."""
        with open(filename, 'wb') as f:
            f.write(self.to_xml(nsmap))

    def recursive_find(self, element, tag: str) -> List:
        """
        Recursively find all elements in the METS object tree with the given tag.
        """
        found = []
        if element.tag == tag:
            found.append(element)
        for child in element.children:
            found.extend(self.recursive_find(child, tag))
        return found

    def recursive_find_first(self, element, tag: str, attr_key: str = None, attr_value: str = None) -> Optional:
        """
        Recursively find the first element with the given tag. If attr_key and attr_value are
        provided, the element is returned only if its attribute matches the given value.
        """
        if element.tag == tag:
            if attr_key is None or element.attributes.get(attr_key) == attr_value:
                return element
        for child in element.children:
            result = self.recursive_find_first(child, tag, attr_key, attr_value)
            if result is not None:
                return result
        return None

    @staticmethod
    def extract_use_tags_from_element(element) -> List[str]:
        """
        Extract all 'USE' attribute values from 'file' elements within 'fileGrp' structures
        inside the provided 'fileSec' element.
        """
        use_tags = []

        def recurse_element(xml_element):
            for xml_child in xml_element.children:
                if xml_child.attributes.get("USE", False):
                    recurse_element(xml_child)
                elif isinstance(xml_child, File):
                    use = xml_child.attributes.get("USE")
                    if use is not None:
                        use_tags.append(use)

        for child in element.children:
            if child.attributes.get("USE", False):
                recurse_element(child)

        return use_tags

@dispatch()
class MetsHdr(MetsElement):
    tag = "metsHdr"
    allowed_attributes = {
        "RECORDSTATUS": None,
        "CREATEDATE": None,
        "LASTMODDATE": None,
        "ID": None
    }
    allowed_children = ["agent", "altRecordID", "metsDocumentID"]


@dispatch()
class Agent(MetsElement):
    tag = "agent"
    allowed_attributes = {"ROLE": None, "TYPE": None, "OTHERTYPE": None, "OTHERROLE": None}
    allowed_children = ["name", "note"]

@dispatch()
class Name(MetsElement):
    tag = "name"
    allowed_attributes = {"type": None, "authority": None, "authorityURI": None,
                          "valueURI": None}
    allowed_children = ["namePart", "role", "displayForm"]
    allows_content = True

@dispatch()
class Note(MetsElement):
    tag = "note"
    allowed_attributes = {"type": None}
    allows_content = True

@dispatch()
class AltRecordID(MetsElement):
    tag = "altRecordID"
    allowed_attributes = {"TYPE": None}
    allows_content = True

@dispatch()
class MetsDocumentID(MetsElement):
    tag = "metsDocumentID"
    allowed_attributes = {"TYPE": None}
    allows_content = True

@dispatch()
class DmdSec(MetsElement):
    tag = "dmdSec"
    allowed_attributes = {"ID": None}
    allowed_children = ["mdRef", "mdWrap", "amdSec", "fileSec", "structMap", "dmdSec", "structLink"]

@dispatch()
class MdRef(MetsElement):
    tag = "mdRef"
    allowed_attributes = {
        "LOCTYPE": None,
        "MDTYPE": None,
        "OTHERMDTYPE": None,
        XLINK + "href": None
    }
    allows_content = True

@dispatch()
class AmdSec(MetsElement):
    tag = "amdSec"
    allowed_attributes = {"ID": None}
    allowed_children = ["techMD", "rightsMD", "sourceMD", "digiprovMD"]

@dispatch()
class TechMD(MetsElement):
    tag = "techMD"
    allowed_attributes = {"ID": None}
    allowed_children = ["mdWrap", "mdRef"]

@dispatch()
class RightsMD(MetsElement):
    tag = "rightsMD"
    allowed_attributes = {"ID": None}
    allowed_children = ["mdWrap", "mdRef"]

@dispatch()
class SourceMD(MetsElement):
    tag = "sourceMD"
    allowed_attributes = {"ID": None}
    allowed_children = ["mdWrap", "mdRef"]

@dispatch()
class DigiprovMD(MetsElement):
    tag = "digiprovMD"
    allowed_attributes = {"ID": None}
    allowed_children = ["mdWrap", "mdRef"]

@dispatch()
class MdWrap(MetsElement):
    tag = "mdWrap"
    allowed_attributes = {"MDTYPE": None, "ID": None, "MIMETYPE": None, "OTHERMDTYPE": None}
    allowed_children = ["xmlData"]

@dispatch()
class XMLData(MetsElement):
    tag = "xmlData"
    allows_content = True
    allowed_attributes = {"ID": None}

    def add_child(self, child):
        """
        Override: Accept any child (even if its tag is not in allowed_children)
        because xmlData may embed arbitrary XML.
        """
        self.children.append(child)

@dispatch()
class FileSec(MetsElement):
    tag = "fileSec"
    allowed_attributes = {"ID": None}
    allowed_children = ["fileGrp"]

@dispatch()
class FileGrp(MetsElement):
    tag = "fileGrp"
    allowed_attributes = {"ID": None, "USE": None}
    allowed_children = ["file", "fileGrp"]

@dispatch()
class File(MetsElement):
    tag = "file"
    allowed_attributes = {
        "ID": None, "SEQ": None, "MIMETYPE": None, "USE": None, "CREATED": None,
        "CHECKSUM": None, "CHECKSUMTYPE": None, "SIZE": None,
        "ADMID": None, "OWNERID": None
    }
    allowed_children = ["FLocat"]

@dispatch()
class FLocat(MetsElement):
    tag = "FLocat"
    allowed_attributes = {"LOCTYPE": None,
                          "OTHERLOCTYPE": None,
                          XLINK + "type": None,
                          XLINK + "href": None,
                          "ID": None}
    allows_content = True

@dispatch()
class StructMap(MetsElement):
    tag = "structMap"
    allowed_attributes = {"ID": None, "TYPE": None}
    allowed_children = ["div"]

@dispatch()
class Div(MetsElement):
    tag = "div"
    allowed_attributes = {
        "DMDID": None, "TYPE": None, "ID": None, "ORDER": None,
        "ORDERLABEL": None, "LABEL": None, "ADMID": None,
        "CONTENTIDS": None
    }
    allowed_children = ["mptr", "fptr", "div"]

@dispatch()
class Fptr(MetsElement):
    tag = "fptr"
    allowed_attributes = {"FILEID": None}
    allowed_children = ["area", "seq"]
    allows_content = True

@dispatch()
class Par(MetsElement):
    tag = "par"
    allowed_attributes = {"ID": None}
    allowed_children = ["area", "seq"]

@dispatch()
class Area(MetsElement):
    tag = "area"
    allowed_attributes = {
        "ID": None, "FILEID": None, "SHAPE": None, "COORDS": None,
        "BEGIN": None, "END": None, "BETYPE": None, "EXTENT": None,
        "EXTYPE": None, "ADMID": None, "CONTENT": None, "IDS": None
    }
    allows_content = True

@dispatch()
class StructLink(MetsElement):
    tag = "structLink"
    allowed_attributes = {"ID": None}
    allowed_children = ["smLink"]

@dispatch()
class SmLink(MetsElement):
    tag = "smLink"
    allowed_attributes = {
        "ID": None,
        XLINK + "arcrole": None,
        XLINK + "title": None,
        XLINK + "actuate": None,
        XLINK + "to": None,
        XLINK + "from": None
    }
    allows_content = True

@dispatch()
class BehaviorSec(MetsElement):
    tag = "behaviorSec"
    allowed_attributes = {"ID": None, "CREATED": None, "LABEL": None}
    allowed_children = ["behaviorSec", "behavior"]

@dispatch()
class Behavior(MetsElement):
    tag = "behavior"
    allowed_attributes = {
        "ID": None, "STRUCTID": None, "BTYPE": None,
        "CREATED": None, "LABEL": None, "GROUPID": None,
        "ADMID": None
    }
    allowed_children = ["interfaceDef", "mechanism"]

@dispatch()
class InterfaceDef(MetsElement):
    tag = "interfaceDef"
    allowed_attributes = {"ID": None, "LABEL": None, "LOCTYPE": None, "OTHERLOCTYPE": None}
    allows_content = True

@dispatch()
class Mechanism(MetsElement):
    tag = "mechanism"
    allowed_attributes = {"ID": None, "LABEL": None, "LOCTYPE": None, "OTHERLOCTYPE": None}
    allows_content = True

@dispatch()
class TrpDocMetadata(MetsElement):
    tag = "trpDocMetadata"
    allowed_attributes = {"ID": None, "LABEL": None, "LOCTYPE": None, "OTHERLOCTYPE": None}
    allows_content = True
    allowed_children = [
        "docId", "title", "uploadTimestamp", "uploader", "uploaderId",
        "nrOfPages", "pageId", "url", "thumbUrl", "status", "fimgStoreColl",
        "localFolder", "origDocId", "collectionList", "isInMain"
    ]

@dispatch()
class DocId(MetsElement):
    tag = "docId"
    allows_content = True

@dispatch()
class Title(MetsElement):
    tag = "title"
    allows_content = True

@dispatch()
class UploadTimestamp(MetsElement):
    tag = "uploadTimestamp"
    allows_content = True

@dispatch()
class Uploader(MetsElement):
    tag = "uploader"
    allows_content = True

@dispatch()
class UploaderId(MetsElement):
    tag = "uploaderId"
    allows_content = True

@dispatch()
class NrOfPages(MetsElement):
    tag = "nrOfPages"
    allows_content = True

@dispatch()
class PageId(MetsElement):
    tag = "pageId"
    allows_content = True

@dispatch()
class Url(MetsElement):
    tag = "url"
    allowed_attributes = {"access": None,}
    allows_content = True

@dispatch()
class ThumbUrl(MetsElement):
    tag = "thumbUrl"
    allows_content = True

@dispatch()
class Status(MetsElement):
    tag = "status"
    allows_content = True

@dispatch()
class FimgStoreColl(MetsElement):
    tag = "fimgStoreColl"
    allows_content = True

@dispatch()
class LocalFolder(MetsElement):
    tag = "localFolder"
    allows_content = True

@dispatch()
class OrigDocId(MetsElement):
    tag = "origDocId"
    allows_content = True

@dispatch()
class CollectionList(MetsElement):
    tag = "collectionList"
    allowed_attributes = {}
    allows_content = False
    allowed_children = ["colList"]

@dispatch()
class ColList(MetsElement):
    tag = "colList"
    allowed_attributes = {}
    allows_content = False
    allowed_children = [
        "colId", "colName", "description", "crowdsourcing", "elearning", "nrOfDocuments"
    ]

@dispatch()
class ColId(MetsElement):
    tag = "colId"
    allows_content = True

@dispatch()
class ColName(MetsElement):
    tag = "colName"
    allows_content = True

@dispatch()
class Description(MetsElement):
    tag = "description"
    allows_content = True

@dispatch()
class Crowdsourcing(MetsElement):
    tag = "crowdsourcing"
    allows_content = True

@dispatch()
class Elearning(MetsElement):
    tag = "elearning"
    allows_content = True

@dispatch()
class NrOfDocuments(MetsElement):
    tag = "nrOfDocuments"
    allows_content = True

@dispatch()
class IsInMain(MetsElement):
    tag = "isInMain"
    allows_content = True

@dispatch()
class Mptr(MetsElement):
    tag = "mptr"
    allowed_attributes = {
        "LOCTYPE": None,
        "OTHERLOCTYPE": None,
        XLINK + "href": None,
        XLINK + "role": None,
        XLINK + "arcrole": None,
        XLINK + "title": None,
        XLINK + "show": None,
        XLINK + "actuate": None,
        "ID": None
    }
    allows_content = True

@dispatch()
class Mods(MetsElement):
    tag = "mods"
    allowed_attributes = {'version': None, XSI + 'schemaLocation': None}
    allowed_children = [
        "classification", "relatedItem", "identifier", "recordInfo", "physicalDescription",
        "titleInfo", "originInfo", "part", "language", "location", "typeOfResource", "note",
        "accessCondition", "extension", "name", "subject"
    ]

@dispatch()
class Info(MetsElement):
    tag = "info"
    allowed_attributes = {"version": None}
    allows_content = True

@dispatch()
class Version(MetsElement):
    tag = "version"
    allows_content = True

@dispatch()
class Classification(MetsElement):
    tag = "classification"
    allowed_attributes = {"authority": None}
    allows_content = True

@dispatch()
class RelatedItem(MetsElement):
    tag = "relatedItem"
    allowed_attributes = {"type": None, "displayLabel": None}
    allowed_children = ["recordInfo", "titleInfo", "originInfo", "part",
                        "typeOfResource", "language", "note", "classification", "relatedItem", "identifier",
                        "location", "extension", "name", "subject", "accessCondition"]
    allows_content = True

@dispatch()
class RecordInfo(MetsElement):
    tag = "recordInfo"
    allowed_children = ["recordIdentifier", "recordCreationDate", "recordChangeDate", "descriptionStandard"]
    allows_content = True

@dispatch()
class RecordIdentifier(MetsElement):
    tag = "recordIdentifier"
    allowed_attributes = {"source": None}
    allows_content = True

@dispatch()
class Identifier(MetsElement):
    tag = "identifier"
    allowed_attributes = {"type": None}
    allows_content = True

@dispatch()
class PhysicalDescription(MetsElement):
    tag = "physicalDescription"
    allowed_children = ["digitalOrigin", "extent", "note"]
    allows_content = True

@dispatch()
class DigitalOrigin(MetsElement):
    tag = "digitalOrigin"
    allows_content = True

@dispatch()
class TitleInfo(MetsElement):
    tag = "titleInfo"
    allowed_children = ["title", "subTitle", "nonSort"]
    allows_content = True

@dispatch()
class SubTitle(MetsElement):
    tag = "subTitle"
    allows_content = True

@dispatch()
class OriginInfo(MetsElement):
    tag = "originInfo"
    allowed_children = ["dateIssued", "place", "publisher", "issuance", "edition"]
    allows_content = True

@dispatch()
class Edition(MetsElement):
    tag = "edition"
    allows_content = True

@dispatch()
class Publisher(MetsElement):
    tag = "publisher"
    allows_content = True

@dispatch()
class Issuance(MetsElement):
    tag = "issuance"
    allows_content = True

@dispatch()
class DateIssued(MetsElement):
    tag = "dateIssued"
    allowed_attributes = {"encoding": None, "keyDate": None, "point": None}
    allows_content = True

@dispatch()
class Place(MetsElement):
    tag = "place"
    allowed_children = ["placeTerm"]
    allows_content = True

@dispatch()
class PlaceTerm(MetsElement):
    tag = "placeTerm"
    allowed_attributes = {"type": None}
    allows_content = True

@dispatch()
class Part(MetsElement):
    tag = "part"
    allowed_attributes = {"order": None, "type": None}
    allowed_children = ["detail", "date"]
    allows_content = True

@dispatch()
class Detail(MetsElement):
    tag = "detail"
    allowed_attributes = {"type": None}
    allowed_children = ["number"]
    allows_content = True

@dispatch()
class Number(MetsElement):
    tag = "number"
    allows_content = True

@dispatch()
class Language(MetsElement):
    tag = "language"
    allowed_children = ["languageTerm"]
    allows_content = True

@dispatch()
class LanguageTerm(MetsElement):
    tag = "languageTerm"
    allowed_attributes = {"authority": None, "type": None}
    allows_content = True

@dispatch()
class Location(MetsElement):
    tag = "location"
    allowed_children = ["physicalLocation", "shelfLocator", "location", "extension", "recordInfo",
                        "accessCondition", "part", "url"]
    allows_content = True

@dispatch()
class PhysicalLocation(MetsElement):
    tag = "physicalLocation"
    allowed_attributes = {"valueURI": None}
    allows_content = True

@dispatch()
class Rights(MetsElement):
    tag = "rights"
    allowed_children = ["owner", "ownerLogo", "ownerSiteURL", "ownerContact", "license"]
    allows_content = True

@dispatch()
class Owner(MetsElement):
    tag = "owner"
    allows_content = True

@dispatch()
class OwnerLogo(MetsElement):
    tag = "ownerLogo"
    allows_content = True

@dispatch()
class OwnerSiteURL(MetsElement):
    tag = "ownerSiteURL"
    allows_content = True

@dispatch()
class OwnerContact(MetsElement):
    tag = "ownerContact"
    allows_content = True

@dispatch()
class License(MetsElement):
    tag = "license"
    allows_content = True

@dispatch()
class Links(MetsElement):
    tag = "links"
    allowed_children = ["reference", "presentation", "iiif", "sru"]
    allows_content = True

@dispatch()
class Reference(MetsElement):
    tag = "reference"
    allows_content = True

@dispatch()
class Presentation(MetsElement):
    tag = "presentation"
    allows_content = True

@dispatch()
class TypeOfResource(MetsElement):
    tag = "typeOfResource"
    allowed_attributes = {"collection": None}
    allows_content = True

@dispatch()
class ShelfLocator(MetsElement):
    tag = "shelfLocator"
    allows_content = True
    allowed_children = ['a', 'b', 'i', ]

@dispatch()
class AccessCondition(MetsElement):
    tag = "accessCondition"
    allows_content = True
    allowed_attributes = {
        "type": None,
        XLINK + "href": None,
        "displayLabel": None
    }

@dispatch()
class Extension(MetsElement):
    tag = "extension"
    allows_content = True
    allowed_children = ['externalType', 'info', 'id', 'odid', 'datatype', 'type', 'state']

@dispatch()
class ExternalType(MetsElement):
    tag = "externalType"
    allowed_attributes = {"recordSyntax": None, "code": None}
    allows_content = True

@dispatch()
class RecordCreationDate(MetsElement):
    tag = "recordCreationDate"
    allowed_attributes = {"encoding": None}
    allows_content = True

@dispatch()
class RecordChangeDate(MetsElement):
    tag = "recordChangeDate"
    allowed_attributes = {"encoding": None}
    allows_content = True

@dispatch()
class DescriptionStandard(MetsElement):
    tag = "descriptionStandard"
    allows_content = True

@dispatch()
class VlId(MetsElement):
    tag = "id"
    allows_content = True

@dispatch()
class VlOdid(MetsElement):
    tag = "odid"
    allows_content = True

@dispatch()
class VlDatatype(MetsElement):
    tag = "datatype"
    allows_content = True

@dispatch()
class VlType(MetsElement):
    tag = "type"
    allows_content = True

@dispatch()
class VlState(MetsElement):
    tag = "state"
    allows_content = True

@dispatch()
class Date(MetsElement):
    tag = "date"
    allowed_attributes = {"encoding": None}
    allows_content = True

@dispatch()
class IIIF(MetsElement):
    tag = "iiif"
    allows_content = True

@dispatch()
class Sru(MetsElement):
    tag = "sru"
    allows_content = True

@dispatch()
class NonSort(MetsElement):
    tag = "nonSort"
    allows_content = True

@dispatch()
class NamePart(MetsElement):
    tag = "namePart"
    allowed_attributes = {"type": None, "authority": None}
    allows_content = True

@dispatch()
class Role(MetsElement):
    tag = "role"
    allowed_children = ["roleTerm"]
    allows_content = True

@dispatch()
class RoleTerm(MetsElement):
    tag = "roleTerm"
    allowed_attributes = {"type": None, "authority": None}
    allows_content = True

@dispatch()
class Subject(MetsElement):
    tag = "subject"
    allowed_children = [
        "topic", "geographic", "temporal", "name", "titleInfo", "genre",
        "occupation", "hierarchicalGeographic", "cartographics", "geographicCode",
        "language", "subject"
    ]
    allows_content = True

@dispatch()
class Topic(MetsElement):
    tag = "topic"
    allowed_attributes = {"type": None, "authority": None, "authorityURI": None, "valueURI": None}
    allows_content = True

@dispatch()
class Geographic(MetsElement):
    tag = "geographic"
    allows_content = True

@dispatch()
class Temporal(MetsElement):
    tag = "temporal"
    allows_content = True

@dispatch()
class Extent(MetsElement):
    tag = "extent"
    allows_content = True

@dispatch()
class DisplayForm(MetsElement):
    tag = "displayForm"
    allows_content = True


def add_dynamic_tag(tag_name: str):
    class_name = tag_name[0].upper() + tag_name[1:]  # Capitalize or adjust as needed

    # Create a new class with the desired name
    new_class = type(
        class_name,                # 👈 This becomes the class name
        (MetsElement,),           # 👈 Inherit from MetsElement
        {
            "tag": tag_name,
            "allowed_attributes": {},
            "allowed_children": [],
            "allows_content": True
        }
    )

    # Register in the dispatch dictionary
    METS_MODS_DISPATCH[tag_name] = new_class
    return new_class

def download_file_from_flocat(file: File, output_folder: Path, nametag: str = None, overwrite: bool = False):
    requests.packages.urllib3.disable_warnings()

    mimetype = file.attributes.get("MIMETYPE", "image/jpeg").lower()
    img_ext = MIME_IMAGE_EXTENSIONS.get(mimetype, "")

    for child in file.children:
        if not isinstance(child, FLocat):
            continue

        href = child.attributes.get("{http://www.w3.org/1999/xlink}href")
        if not href:
            continue

        try:
            # Determine base filename
            if nametag:
                filename = file.attributes.get(nametag)
                if not filename:
                    print(f"Warning: Attribute '{nametag}' not found. Falling back to filename from href.")
                    filename = Path(href).name
                else:
                    # Add extension from href if it exists
                    href_ext = Path(href).suffix
                    filename += href_ext if href_ext else img_ext
            else:
                filename = Path(href).name

            # Ensure file has extension
            if not Path(filename).suffix and img_ext:
                filename += img_ext

            target_path = output_folder / filename
            print(f"Downloading {href} -> {target_path}")

            if target_path.exists() and not overwrite:
                print("Already exists and skipped! Use 'overwrite=True' to force download.")
                continue

            response = requests.get(
                href,
                timeout=20,
                verify=False,
                headers={"User-Agent": "Mozilla/5.0"}
            )
            response.raise_for_status()

            with open(target_path, "wb") as f:
                f.write(response.content)

        except Exception as e:
            print(f"Failed to download {href}: {e}")

def parse_mets_xml_multiple_roots(xml_source, loose=False, verbose=False) -> List[Mets]:
    """
    Parse XML content containing multiple <mets:mets> root elements using pattern matching.

    :param xml_source: Path, bytes, or file-like object.
    :param loose: Whether to skip unknown elements.
    :param verbose: debug
    :return: List of Mets objects.
    """
    if isinstance(xml_source, str) and Path(xml_source).exists():
        with open(xml_source, 'r', encoding='utf-8') as f:
            content = f.read()
    elif isinstance(xml_source, (bytes, bytearray)):
        content = xml_source.decode('utf-8')
    else:
        content = xml_source.read().decode('utf-8')

    mets_elements = []

    # Regex to find full <mets:mets ...> ... </mets:mets> blocks
    pattern = re.compile(r"(<(?:mets:)?mets[^>]*>)(.*?)(</(?:mets:)?mets>)", re.DOTALL)

    for match in pattern.finditer(content):
        full_block = match.group(0)
        # Parse each block as standalone XML
        try:
            parsed = parse_mets_xml(BytesIO(full_block.encode('utf-8')), loose=loose, verbose=verbose)
            if parsed:
                mets_elements.append(parsed)
        except Exception as e:
            if not loose:
                raise MetsError(f"Error parsing METS block: {e}")
            if verbose:
                print(f"Error parsing METS block: {e}")
            # else skip silently
    return mets_elements


def parse_mets_xml(mets, loose=False, verbose=False) -> Mets | None:
    """
    Parse a METS XML file or file-like object into a corresponding MetsElement object.

    :param mets: Filename or file-like object containing the METS XML.
    :param loose: If True, unknown elements are skipped. Otherwise, an error is raised.
    :param verbose: debug
    :return: The root MetsElement object.
    """
    parent_stack = []
    close_after = False
    if isinstance(mets, str):
        f = open(mets, 'rb')
        close_after = True
    else:
        f = mets
    try:
        # Now iterparse on cleaned tree bytes
        context = etree.iterparse(f, events=("start", "end"), recover=True)

        for event, element in context:
            # Extract local (namespace-free) tag name.
            localname = etree.QName(element.tag).localname
            if localname not in METS_MODS_DISPATCH:
                if loose:
                    if verbose:
                        print(f"WARNING: Add \"{localname}\" dynamically to the xml-object.")
                    METS_MODS_DISPATCH[localname] = add_dynamic_tag(localname)
                else:
                    raise MetsError(f"Element \"{localname}\" not found in dispatch.")
            if event == 'start':
                content = element.text.strip() if element.text and element.text.strip() else None
                if element.attrib and content is not None:
                    obj = METS_MODS_DISPATCH[localname](attributes=element.attrib, content=content, loose=loose, verbose=verbose)
                elif element.attrib:
                    obj = METS_MODS_DISPATCH[localname](attributes=element.attrib, loose=loose, verbose=verbose)
                elif content is not None:
                    obj = METS_MODS_DISPATCH[localname](content=content, loose=loose, verbose=verbose)
                else:
                    obj = METS_MODS_DISPATCH[localname](loose=loose, verbose=verbose)
                parent_stack.append(obj)
            elif event == 'end':
                child = parent_stack.pop()
                if parent_stack:
                    parent_stack[-1].add_child(child)
                else:
                    return child
        raise MetsError("No root element found.")
    finally:
        if close_after:
            f.close()
