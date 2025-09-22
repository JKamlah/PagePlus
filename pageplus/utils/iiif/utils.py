import json
import os
import re
from contextlib import asynccontextmanager
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import aiofiles
from aiohttp import ClientResponse, ClientSession, ClientSSLError, ClientTimeout, ContentTypeError



def check_dir(path):
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"{path.absolute()} does not exist")
    return path


def create_dir(path):
    path = Path(path)
    # do nothing if directory already exists
    path.mkdir(parents=True, exist_ok=True)
    return path


def sanitize_url(url: str, safe: str = "/:=?&#") -> str:
    # try:
    #     return quote(url, safe=safe)
    # except Exception:
    #     return url.strip().replace(" ", "%20")
    return url.replace(" ", "+").replace(" ", "+")


def sanitize_str(string):
    return string.replace("/", "").replace(".", "").replace(":", "").replace("www", "").replace(" ", "_")


async def get_json_async(url: str, allow_insecure: bool = False) -> Dict[str, Any]:
    """
    Args:
        url: The URL to fetch JSON from
        allow_insecure: If True, allows fallback to insecure connection on SSL errors

    Returns: Parsed JSON content
    """

    async def parse_response(res: ClientResponse) -> Dict[str, Any]:
        try:
            return await res.json()
        except ContentTypeError:
            try:
                return json.loads(await res.text())
            except json.JSONDecodeError as e:
                raise ValueError(f"Content could not be parsed as JSON: {str(e)}") from e

    try:
        async with async_request(url) as response:
            return await parse_response(response)
    except ClientSSLError as ssl_error:
        if not allow_insecure:
            raise ssl_error
        # Fallback to insecure connection
        async with async_request(url, ssl=False) as response:
            return await parse_response(response)


@asynccontextmanager
async def async_request(
    url: str,
    method: str = "GET",
    headers: Optional[Dict[str, str]] = None,
    timeout: Optional[int] = None,
    allow_insecure: bool = False,
    **kwargs,
) -> ClientResponse:
    """
    Async context manager for making HTTP requests with proper proxy and error handling.

    Args:
        url: The URL to request
        method: HTTP method (default: "GET")
        headers: Optional dictionary of headers
        timeout: Optional timeout in seconds (default: from config)
        allow_insecure: If True, allows fallback to insecure connection on SSL errors
        **kwargs: Additional arguments to pass to session.request

    Usage:
        async with async_request("https://example.com") as response:
            if response.ok:
                data = await response.read()
    """
    proxy = (
        None
    )

    user_agent = os.getenv("PAGEPLUS_USER_AGENT", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    request_headers = {"User-Agent": user_agent}
    if headers:
        request_headers.update(headers)

    timeout_value = timeout or 120

    try:
        async with ClientSession(trust_env=True, timeout=ClientTimeout(total=timeout_value)) as session:
            async with session.request(
                method, url, headers=request_headers, proxy=proxy, **kwargs
            ) as response:
                yield response
    except ClientSSLError as ssl_error:
        if not allow_insecure:
            raise ssl_error

        ssl_kwargs = {**kwargs, "ssl": False}
        async with ClientSession(trust_env=True, timeout=ClientTimeout(total=timeout_value)) as session:
            async with session.request(
                method, url, headers=request_headers, proxy=proxy, **ssl_kwargs
            ) as response:
                yield response


def get_id(dic):
    """Get ID from a dictionary, handling different ID formats"""
    if isinstance(dic, list):
        dic = dic[0]

    if isinstance(dic, dict):
        try:
            return dic["@id"]
        except KeyError:
            try:
                return dic["id"]
            except KeyError as e:
                raise ValueError(f"[get_id] No id provided: {e}")

    if isinstance(dic, str):
        return dic

    return None


def get_size(img_rsrc, dimension):
    try:
        img_height = img_rsrc[dimension]
    except KeyError:
        return None
    return int(img_height)


class MLStripper(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.reset()
        self.fed = []

    def handle_data(self, d):
        self.fed.append(d)

    def handle_entityref(self, name):
        self.fed.append("&%s;" % name)

    def handle_charref(self, name):
        self.fed.append("&#%s;" % name)

    def get_data(self):
        return "".join(self.fed)


def _strip_once(value):
    """
    Internal tag stripping utility used by strip_tags.
    """
    s = MLStripper()
    s.feed(value)
    s.close()
    return s.get_data()


def strip_tags(value):
    """Return the given HTML with all tags stripped."""
    value = str(value)
    while "<" in value and ">" in value:
        new_value = _strip_once(value)
        if value.count("<") == new_value.count("<"):
            # _strip_once wasn't able to detect more tags.
            break
        value = new_value
    return value


def substrs_in_str(string, substrings):
    for substr in substrings:
        if substr in string:
            return True
    return False


def get_version_nb(lic):
    version = re.findall(r"\d\.\d", lic)
    if len(version):
        return version[0]
    nb = re.findall(r"\d", lic)
    if len(nb):
        return f"{nb[0]}.0"
    return "1.0"


def get_license_url(original_lic):
    lic = str(mono_val(original_lic))

    if not lic:
        return "No license information found"

    lic = unescape(lic)
    # Extract href values
    hrefs = re.findall(r'href=[\'"]?([^\'" >]+)', lic)
    if hrefs:
        if len(hrefs) == 1:
            return hrefs[0]
        lic = " ".join(hrefs)
    lic = strip_tags(lic)

    # Extract potential URLs
    urls = re.findall(r"(https?://[^\s]+|www\.[^\s]+|[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}(?:/[^\s]*)?)", lic)
    if urls:
        if len(urls) == 1:
            # If there's exactly one URL, return it
            lic = urls[0]
            if not lic.startswith("http"):
                lic = f"http://{lic}"  # Default to http for domain-like strings
            return lic

    # If multiple URLs or no URLs, normalize and try matching license_map
    normalized = lic.lower().strip().replace("-", "").replace(" ", "")
    version = get_version_nb(normalized)

    license_map = {
        (
            "publicdomain",
            "cc0",
            "pdm",
        ): "https://creativecommons.org/publicdomain/mark/1.0/",
        ("byncsa", "noncommercialsharealike"): f"by-nc-sa/{version}/",
        ("byncnd", "noncommercialnoderiv"): f"by-nc-nd/{version}/",
        ("bysa", "sharealike"): f"by-sa/{version}/",
        ("bync", "noncommercial"): f"by-nc/{version}/",
        ("bynd", "noderiv"): f"by-nd/{version}/",
        ("by",): f"by/{version}/",
    }

    for terms, url in license_map.items():
        if substrs_in_str(normalized, terms):
            return f"https://creativecommons.org/licenses/{url}" if "publicdomain" not in terms else url

    return lic or "No license information found"


def mono_val(val: Union[str, int, List, Dict]) -> Union[str, int, None]:
    """
    Extracts a single value (str or int) from a potentially nested data structure.
    """
    if isinstance(val, (str, int)):
        return val

    if isinstance(val, dict):
        return mono_val(list(val.values()))

    if isinstance(val, list):
        if not val:
            return None

        if len(val) == 1:
            return mono_val(val[0])

        for item in val:
            try:
                return mono_val(item)
            except (ValueError, TypeError):
                continue

        return None
    return None


def get_meta(metadatum, meta_type="label"):
    """
    Retrieve metadata value based on the specified meta_type ("label" or "value").
    """
    meta_content = metadatum.get(meta_type)

    # Return directly if it's a string
    if isinstance(meta_content, str):
        return meta_content

    # Handle list type: prioritize English language if present
    if isinstance(meta_content, list):
        for lang_label in meta_content:
            if isinstance(lang_label, dict):
                lang = lang_label.get("@language") or lang_label.get("language")
                value = lang_label.get("@value") or lang_label.get("value")
                if lang == "en":
                    return mono_val(value)

    # Handle dictionary type: prioritize English keys
    if isinstance(meta_content, dict):
        if "en" in meta_content:
            return mono_val(meta_content["en"])
        # Return the first key's value if only one exists
        if len(meta_content) == 1:
            return mono_val(next(iter(meta_content.values())))

    # Default: return None if no suitable content found
    return None


def get_meta_value(metadatum, label: str):
    """
    Get the value of a metadata label.
    metadatum = {
        "label": "<fct-param-label>",
        "value": "<value-to-return>"
    }
    """
    meta_label = get_meta(metadatum, "label")
    if meta_label not in [label, label.capitalize(), label.lower(), f"@{label}"]:
        return None
    return get_meta(metadatum, "value")


def write_to_file(path: Path, content: str, mode: Optional[str] = "w"):
    """Thread-safe file writing."""
    with open(path, mode) as f:
        f.write(content)


async def write_chunks(file_path, response):
    async with aiofiles.open(file_path, mode="wb") as file:
        async for chunk in response.content.iter_chunked(8192):
            await file.write(chunk)
