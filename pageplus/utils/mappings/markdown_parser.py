"""Markdown content parser and text cleaner module.

Provides utilities to strip Markdown syntax artifacts (such as '#' headers,
bold/italic markers, inline code, link syntax, blockquotes) from text before
inserting into PAGE XML elements.

Conforms to standard CommonMark specifications to distinguish Markdown syntax
(e.g., '^# Header') from legitimate hash characters in body text (e.g., 'C#', 'Issue #42').
"""
import re
from typing import Any, Dict, List


def strip_markdown_headers(line: str) -> str:
    """Strip ATX header prefix ('# ', '## ', etc.) from a line if present.

    According to CommonMark specs, ATX headers require 1 to 6 '#' characters at
    line start (with up to 3 leading spaces), followed by at least one whitespace character
    or end-of-line.

    Examples:
        '# Header 1' -> 'Header 1'
        '  ### 2. Method' -> '2. Method'
        'C#' -> 'C#' (preserved)
        'Issue #42' -> 'Issue #42' (preserved)
    """
    if not line:
        return line

    # Match 0-3 leading spaces, 1-6 hashes, then required whitespace (or EOL)
    match = re.match(r"^[\t ]{0,3}#{1,6}(?:[\t ]+(.*)|[\t ]*)$", line)
    if match:
        return match.group(1) or ""
    return line


def strip_blockquotes(line: str) -> str:
    """Strip leading blockquote indicator '>' from a line."""
    if not line:
        return line
    res = line
    while True:
        match = re.match(r"^[\t ]*>[\t ]*(.*)$", res)
        if match:
            res = match.group(1)
        else:
            break
    return res


def strip_list_markers(line: str) -> str:
    """Strip list markers ('- ', '* ', '+ ', '1. ', '1) ') from line start."""
    if not line:
        return line

    # Task list check boxes e.g. '[ ] ', '[x] '
    line = re.sub(r"^[\t ]*\[[ xX]\][\t ]+", "", line)
    # Unordered or ordered list items
    match = re.match(r"^[\t ]*(?:[-*+]|\d+[\.\)])[\t ]+(.*)$", line)
    if match:
        return match.group(1)
    return line


def strip_markdown_inline(text: str) -> str:
    """Strip inline Markdown formatting markers from text while keeping the content.

    Handles:
        - Images: ![alt](url) -> alt
        - Links: [text](url) -> text, [text][ref] -> text
        - Bold & Italic: ***text***, **text**, *text*, ___text___, __text__, _text_
        - Strikethrough: ~~text~~ -> text
        - Code spans: `text` -> text
        - Math spans: $$text$$ -> text, $text$ -> text
    """
    if not text:
        return text

    res = text

    # Images: ![alt](url) -> alt
    res = re.sub(r"!\[([^\]]*)\]\([^\)]+\)", r"\1", res)

    # Links: [text](url) or [text][ref] -> text
    res = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", res)
    res = re.sub(r"\[([^\]]+)\]\[[^\]]*\]", r"\1", res)

    # Math blocks/spans: $$math$$ -> math, $math$ -> math
    res = re.sub(r"\$\$([^\$]+)\$\$", r"\1", res)
    res = re.sub(r"\$([^\$]+)\$", r"\1", res)

    # Code spans: `code` -> code
    res = re.sub(r"`([^`]+)`", r"\1", res)

    # Strikethrough: ~~text~~ -> text
    res = re.sub(r"~~([^~]+)~~", r"\1", res)

    # Bold & Italic combinations
    res = re.sub(r"\*\*\*([^\*]+)\*\*\*", r"\1", res)
    res = re.sub(r"\*\*([^\*]+)\*\*", r"\1", res)
    res = re.sub(r"\*([^\*]+)\*", r"\1", res)

    res = re.sub(r"___([^_]+)___", r"\1", res)
    res = re.sub(r"__([^_]+)__", r"\1", res)
    res = re.sub(r"_([^_]+)_", r"\1", res)

    return res


def clean_markdown_line(
    line: str,
    strip_headers: bool = True,
    strip_inline: bool = True,
    strip_bq: bool = True,
    strip_lists: bool = False,
) -> str:
    """Clean Markdown syntax artifacts from a single line of text.

    Args:
        line: Input text line.
        strip_headers: Remove leading ATX '#' header tags.
        strip_inline: Remove bold, italic, code, link, math markup.
        strip_bq: Remove leading blockquote '>' indicators.
        strip_lists: Remove leading list markers ('- ', '1. ').

    Returns:
        Cleaned text string.
    """
    if not line:
        return line

    res = line
    if strip_headers:
        res = strip_markdown_headers(res)
    if strip_bq:
        res = strip_blockquotes(res)
    if strip_lists:
        res = strip_list_markers(res)
    if strip_inline:
        res = strip_markdown_inline(res)

    return res.strip()


def clean_markdown_text(
    text: str,
    strip_headers: bool = True,
    strip_inline: bool = True,
    strip_bq: bool = True,
    strip_lists: bool = False,
) -> str:
    """Clean Markdown syntax artifacts from multi-line text content.

    Preserves line structure while cleaning each line.
    """
    if not text:
        return text

    lines = text.replace("\r\n", "\n").split("\n")
    cleaned_lines = [
        clean_markdown_line(
            line,
            strip_headers=strip_headers,
            strip_inline=strip_inline,
            strip_bq=strip_bq,
            strip_lists=strip_lists,
        )
        for line in lines
    ]
    return "\n".join(cleaned_lines)


def parse_markdown_to_blocks(markdown_text: str) -> List[Dict[str, Any]]:
    """Parse raw Markdown text into structured blocks with clean content.

    Returns a list of dicts:
        {"kind": "heading"|"paragraph"|"table"|"list", "lines": [...], ...}
    """
    blocks: List[Dict[str, Any]] = []
    raw_lines = (markdown_text or "").replace("\r\n", "\n").split("\n")

    i = 0
    n = len(raw_lines)
    while i < n:
        line = raw_lines[i]
        stripped = line.strip()
        if not stripped:
            i += 1
            continue

        # Heading check: '#' followed by space
        heading_match = re.match(r"^[\t ]{0,3}#{1,6}[\t ]+(.*)$", line)
        if heading_match:
            heading_text = clean_markdown_line(heading_match.group(1), strip_headers=False)
            blocks.append({
                "kind": "heading",
                "lines": [heading_text],
            })
            i += 1
            continue

        # Table check
        if "|" in stripped and i + 1 < n and re.match(r"^\s*\|?[\s:|-]+\|?\s*$", raw_lines[i + 1]):
            table_lines: List[str] = []
            while i < n and "|" in raw_lines[i]:
                table_lines.append(raw_lines[i])
                i += 1
            rows: List[List[str]] = []
            for tl in table_lines:
                if re.match(r"^\s*\|?[\s:|-]+\|?\s*$", tl):
                    continue  # separator row
                cells = [strip_markdown_inline(c.strip()) for c in tl.strip().strip("|").split("|")]
                rows.append(cells)
            if rows:
                blocks.append({"kind": "table", "rows": rows})
            continue

        # Paragraph or list block
        para_lines: List[str] = []
        while i < n and raw_lines[i].strip() and not re.match(r"^[\t ]{0,3}#{1,6}[\t ]+", raw_lines[i]):
            if "|" in raw_lines[i] and i + 1 < n and re.match(r"^\s*\|?[\s:|-]+\|?\s*$", raw_lines[i + 1]):
                break
            cleaned = clean_markdown_line(raw_lines[i], strip_lists=True)
            if cleaned:
                para_lines.append(cleaned)
            i += 1
        if para_lines:
            blocks.append({"kind": "paragraph", "lines": para_lines})

    return blocks
