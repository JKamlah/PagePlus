import re
import pandas as pd
from typing import List, Dict, Any
from rich.table import Table


def strip_rich_text(text: str) -> str:
    """Strip rich text formatting from a string."""
    pattern = r"\[(\w+)\](.*?)\[/\1\]"
    matches = re.findall(pattern, text)
    if matches:
        return " ".join(match[1] for match in matches)
    return text  # return original if no matches


def rich_table_to_dataframe(rich_table: Table) -> pd.DataFrame:
    """Convert a rich table to a pandas DataFrame."""
    headers = [strip_rich_text(col.header) for col in rich_table.columns]
    column_cells = []
    for col in rich_table.columns:
        column_cells.append([strip_rich_text(cell) for cell in col._cells])
    data_rows = list(map(list, zip(*column_cells))) if column_cells else []
    return pd.DataFrame(data_rows, columns=headers)
