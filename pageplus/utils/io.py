import sys
from lxml import etree as ET
import langcodes


def setxml(el, name, val):
    el.set(name, str(val))

def xywh_from_points(points_str):
    """
    Given a string of points (e.g. "x1,y1 x2,y2 ..."), compute a bounding box.
    Returns a dict with keys: 'x', 'y', 'w', 'h'.
    """
    pts = []
    for pt in points_str.split():
        try:
            x, y = map(int, pt.split(','))
            pts.append((x, y))
        except Exception:
            continue
    if not pts:
        return {'x': 0, 'y': 0, 'w': 0, 'h': 0}
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    minx, miny = min(xs), min(ys)
    maxx, maxy = max(xs), max(ys)
    return {'x': minx, 'y': miny, 'w': maxx - minx, 'h': maxy - miny}

def set_alto_xywh_from_coords(reg_alto, reg_page, classes=None):
    if classes is None:
        classes = ['HEIGHT', 'WIDTH', 'HPOS', 'VPOS']
    # Assume PAGE element has a child <Coords> with attribute "points"
    coords = reg_page.get_coordinates(returntype='string')
    if coords is None:
        return
    xywh = xywh_from_points(coords)
    mapping = {'HEIGHT': 'h', 'WIDTH': 'w', 'HPOS': 'x', 'VPOS': 'y'}
    for k_alto, k_xywh in mapping.items():
        if k_alto in classes:
            setxml(reg_alto, k_alto, str(xywh[k_xywh]))

def set_alto_shape_from_coords(reg_alto, reg_page):
    # Create a Shape element with a Polygon using the points from PAGE.
    coords = reg_page.get_coordinates(returntype='string')
    shape = ET.SubElement(reg_alto, 'Shape')
    polygon = ET.SubElement(shape, 'Polygon')
    setxml(polygon, 'POINTS', coords)

def set_alto_id_from_page_id(reg_alto, reg_page, suffix=''):
    # Assumes the PAGE element has an attribute "id" (or "ID")
    setxml(reg_alto, 'ID', reg_page.get_id()+suffix)

def set_alto_lang_from_page_lang(reg_alto, reg_page, attribute_name='LANG', langcode=True):
    # Try several attribute names for language.
    lang = reg_page.get_language()
    if lang:
        if langcode:
            lang = langcodes.find(lang).to_alpha3()
        setxml(reg_alto, attribute_name, lang)

def get_nth_textequiv(reg_page, textequiv_index, textequiv_fallback_strategy):
    """
    Return the text from a PAGE element's TextEquiv/Unicode subelement.
    """
    textequivs = reg_page.findall(".//TextEquiv")
    if not textequivs:
        if textequiv_fallback_strategy == 'raise':
            raise ValueError("PAGE element '%s' has no TextEquivs" % (reg_page.get("id") or ""))
        return ''
    for te in textequivs:
        if te.get("index") and int(te.get("index")) == textequiv_index:
            unicode_el = te.find("Unicode")
            if unicode_el is not None:
                return unicode_el.text or ""
    if textequiv_fallback_strategy == 'raise':
        raise ValueError("PAGE element '%s' has no TextEquiv index %d" % (reg_page.get("id") or "", textequiv_index))
    elif textequiv_fallback_strategy == 'first':
        unicode_el = textequivs[0].find("Unicode")
        return unicode_el.text if unicode_el is not None else ""
    else:  # 'last'
        unicode_el = textequivs[-1].find("Unicode")
        return unicode_el.text if unicode_el is not None else ""

def contains(el, bbox):
    """
    Check if the bounding box (minx, miny, maxx, maxy) is contained within
    the element's coordinates (assumed in attributes HPOS, VPOS, WIDTH, HEIGHT).
    """
    minx1, miny1, maxx1, maxy1 = bbox
    minx2 = int(el.get('HPOS'))
    miny2 = int(el.get('VPOS'))
    maxx2 = minx2 + int(el.get('WIDTH'))
    maxy2 = miny2 + int(el.get('HEIGHT'))
    if minx1 < minx2:
        return False
    if maxx1 > maxx2:
        return False
    if miny1 < miny2:
        return False
    if maxy1 > maxy2:
        return False
    return True

# Mapping of PAGE region types to ALTO block types.
REGION_PAGE_TO_ALTO = {
    "TextRegion": "TextBlock",
    "SeparatorRegion": "GraphicalElement",
    "GraphicRegion": "Illustration",
    "LineDrawingRegion": "Illustration",
    "ChartRegion": "Illustration",
    "ImageRegion": "Illustration",
    "TableRegion": "ComposedBlock",
    # Other types can be added if needed.
    "MathsRegion": None,
    "ChemRegion": None,
    "MusicRegion": None,
    "AdvertRegion": None,
    "NoiseRegion": None,
    "UnknownRegion": None,
    "CustomRegion": None,
}

HYPHEN_CHARS = ['-', '⸗', '=', '¬', '­']