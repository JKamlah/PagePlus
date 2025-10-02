import re
import unicodedataplus as unicodedata
from functools import lru_cache

# A simple mapping for plane names.
# For a more comprehensive solution, a dedicated library might be better.
PLANE_NAMES = {
    0: "Basic Multilingual Plane (BMP)",
    1: "Supplementary Multilingual Plane (SMP)",
    2: "Supplementary Ideographic Plane (SIP)",
    3: "Tertiary Ideographic Plane (TIP)",
    14: "Supplementary Special-purpose Plane (SSP)",
    15: "Private Use Area (PUA)",
    16: "Private Use Area (PUA)",
}

@lru_cache(maxsize=None)
def get_char_data(char):
    """
    Returns a dictionary of Unicode properties for a given character.
    Caches results for performance.
    """
    if not isinstance(char, str) or len(char) != 1:
        return None
    
    try:
        codepoint = ord(char)
        name = unicodedata.name(char, "N/A")
        block = unicodedata.block(char)
        category = unicodedata.category(char)
        script = unicodedata.script(char)
        
        # Determine the plane
        plane = codepoint >> 16
        plane_name = PLANE_NAMES.get(plane, "Reserved/Unassigned")

        return {
            "glyph": char,
            "codepoint": codepoint,
            "hex": f"U+{codepoint:04X}",
            "name": name,
            "category": category,
            "block": block,
            "script": script,
            "plane": plane_name,
        }
    except (TypeError, ValueError):
        return None

def name_codepoints(search_term, regex=False, exact=False):
    """
    Finds codepoints by character name.
    'unicodedataplus' does not support regex search, so we will emulate it.
    """
    results = set()
    if exact:
        try:
            # unicodedata.lookup() is the standard way for exact name matching
            char = unicodedata.lookup(search_term)
            results.add(ord(char))
        except KeyError:
            pass # No character with this name
    else:
        # Iterate through all codepoints to find matches. This can be slow.
        # unicodedataplus may have a better way, but this is a direct approach.
        for i in range(0x110000):
            try:
                name = unicodedata.name(chr(i))
                if (regex and re.search(search_term, name, re.IGNORECASE)) or \
                   (not regex and search_term.lower() in name.lower()):
                    results.add(i)
            except ValueError:
                continue
        return list(results)

def get_codepoint_data(codepoint):
    """
    Returns a dictionary of Unicode properties for a given codepoint.
    """
    try:
        char = chr(codepoint)
        return get_char_data(char)
    except (TypeError, ValueError):
        return None
