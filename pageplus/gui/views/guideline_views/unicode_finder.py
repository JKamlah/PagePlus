import streamlit as st
import pandas as pd
import unicodedataplus as unicodedata


def get_unicode_plane(codepoint):
    if 0x0000 <= codepoint <= 0xFFFF:
        return "Mehrsprachige Basis-Ebene (BMP)"
    elif 0x10000 <= codepoint <= 0x1FFFF:
        return "Supplementäre mehrsprachige Ebene (SMP)"
    elif 0x20000 <= codepoint <= 0x2FFFF:
        return "Supplementäre ideographische Ebene (SIP)"
    elif 0x30000 <= codepoint <= 0x3FFFF:
        return "Tertiäre ideographische Ebene (TIP)"
    elif 0xE0000 <= codepoint <= 0xE0FFF:
        return "Supplementäre Sonderebene (SSP)"
    else:
        return "N/A"


def unicode_finder_view():
    st.header("Unicode Finder")

    with st.form("unicode_search_form"):
        search_by = st.selectbox("Search for", ["Glyph", "Codepoint", "Name", "Hex"])
        search_term = st.text_input("Search term")
        submitted = st.form_submit_button("Search")

        if submitted:
            if search_term:
                results = []
                seen_hex = set()

                if search_by == "Glyph":
                    for char in search_term:
                        codepoint = ord(char)
                        hex_val = f"0x{codepoint:04X}"
                        if hex_val in seen_hex:
                            continue
                        try:
                            name = unicodedata.name(char, "N/A")
                            block = unicodedata.block(char)
                            category = unicodedata.category(char)
                            script = unicodedata.script(char)
                            plane = get_unicode_plane(codepoint)
                            results.append({
                                "Glyph": char,
                                "Unicodepoint": codepoint,
                                "Hex": hex_val,
                                "Name": name,
                                "Block": block,
                                "Ebene": plane,
                                "Schrift": script,
                                "Kategorie": category
                            })
                            seen_hex.add(hex_val)
                        except TypeError:
                            continue  # Skip invalid characters
                elif search_by == "Codepoint":
                    try:
                        codepoint = int(search_term)
                        hex_val = f"0x{codepoint:04X}"
                        if hex_val not in seen_hex:
                            char = chr(codepoint)
                            name = unicodedata.name(char, "N/A")
                            block = unicodedata.block(char)
                            category = unicodedata.category(char)
                            script = unicodedata.script(char)
                            plane = get_unicode_plane(codepoint)
                            results.append({
                                "Glyph": char,
                                "Unicodepoint": codepoint,
                                "Hex": hex_val,
                                "Name": name,
                                "Block": block,
                                "Ebene": plane,
                                "Schrift": script,
                                "Kategorie": category
                            })
                            seen_hex.add(hex_val)
                    except (ValueError, TypeError):
                        st.error("Invalid codepoint. Please enter a valid integer.")
                elif search_by == "Name":
                    for i in range(0x110000):
                        try:
                            name = unicodedata.name(chr(i))
                            if search_term.lower() in name.lower():
                                hex_val = f"0x{i:04X}"
                                if hex_val in seen_hex:
                                    continue
                                char = chr(i)
                                block = unicodedata.block(char)
                                category = unicodedata.category(char)
                                script = unicodedata.script(char)
                                plane = get_unicode_plane(i)
                                results.append({
                                    "Glyph": char,
                                    "Unicodepoint": i,
                                    "Hex": hex_val,
                                    "Name": name,
                                    "Block": block,
                                    "Ebene": plane,
                                    "Schrift": script,
                                    "Kategorie": category
                                })
                                seen_hex.add(hex_val)
                        except ValueError:
                            continue
                elif search_by == "Hex":
                    try:
                        codepoint = int(search_term, 16)
                        hex_val = f"0x{codepoint:04X}"
                        if hex_val not in seen_hex:
                            char = chr(codepoint)
                            name = unicodedata.name(char, "N/A")
                            block = unicodedata.block(char)
                            category = unicodedata.category(char)
                            script = unicodedata.script(char)
                            plane = get_unicode_plane(codepoint)
                            results.append({
                                "Glyph": char,
                                "Unicodepoint": codepoint,
                                "Hex": hex_val,
                                "Name": name,
                                "Block": block,
                                "Ebene": plane,
                                "Schrift": script,
                                "Kategorie": category
                            })
                            seen_hex.add(hex_val)
                    except (ValueError, TypeError):
                        st.error("Invalid hex value. Please enter a valid hex number (e.g., 0x0041 or E000).")

                if results:
                    df = pd.DataFrame(results)
                    st.dataframe(df)
                else:
                    st.info("No results found.")
            else:
                st.warning("Please enter a search term.")
