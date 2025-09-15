from typing import Any, Dict, List, Optional
from importlib import util

import pandas as pd

# Conditionally import transkribus components
if util.find_spec('transkribus_utils'):
    from pageplus.cli.transkribus import (
        DataFilter,
        PageStatus,
        Role,
        find_documents,
        load_document,
        set_credentials,
        set_url,
        show_settings,
        update_document,
        install
    )
    TRANSKRIBUS_INSTALLED = True
else:
    from pageplus.cli.transkribus import install
    PageStatus = str
    Role = str
    DataFilter = str
    TRANSKRIBUS_INSTALLED = False

from pageplus.gui.cli_bridges.base import CLIBridge, capture_output

from io import StringIO
import sys


class TranskribusBridge(CLIBridge):
    def is_installed(self) -> bool:
        """Check if transkribus_utils is installed."""
        return TRANSKRIBUS_INSTALLED

    def install(self) -> dict:
        """Install the Transkribus connector."""
        try:
            output = capture_output(install)
            return {"success": True, "output": output}
        except Exception as e:
            return {"success": False, "output": str(e)}

    def find_documents(
        self,
        filter_by: List[str],
        search_term: List[str],
        case_sensitive: bool = False
    ) -> Dict[str, Any]:
        """Find documents in Transkribus."""
        try:
            df = find_documents(
                filter_by=filter_by,
                search_term=search_term,
                case_sensitive=case_sensitive
            )
            if isinstance(df, pd.DataFrame):
                return {"success": True, "output": df}
            else:
                # find_documents might return None or something else on failure before raising exception
                return {"success": False, "output": "Failed to retrieve documents."}
        except Exception as e:
            return {"success": False, "output": str(e)}

    def load_document(
        self,
        collection_id: int,
        document_id: int,
        pages: List[str],
        load_images: bool,
        folderpath: Optional[str],
        workspace: str,
        overwrite_ws: bool,
        loading: bool
    ) -> Dict[str, Any]:
        """Load a document from Transkribus."""
        try:
            load_document(
                collection_id=collection_id,
                document_id=document_id,
                pages=pages,
                load_images=load_images,
                folderpath=folderpath,
                workspace=workspace,
                overwrite_ws=overwrite_ws,
                loading=loading,
            )
            return {"success": True, "output": "Document loaded successfully."}
        except Exception as e:
            return {"success": False, "output": str(e)}

    def update_document(
        self,
        inputs: List[str],
        collection_id: int,
        document_id: int,
        pages: List[str],
        overwrite: bool,
        status: PageStatus,
        note: str,
    ) -> Dict[str, Any]:
        """Update a document in Transkribus."""
        try:
            update_document(
                inputs=inputs,
                collection_id=collection_id,
                document_id=document_id,
                pages=pages,
                overwrite=overwrite,
                status=status,
                note=note,
                parent=-1,
                nr_is_page_id=False,
                tool_name="PagePlusGUI"
            )
            return {"success": True, "output": "Document updated successfully."}
        except Exception as e:
            return {"success": False, "output": str(e)}

    def set_url(self, url: str) -> Dict[str, Any]:
        """Set Transkribus API URL."""
        try:
            set_url(url)
            return {"success": True, "output": f"URL set to {url}"}
        except Exception as e:
            return {"success": False, "output": str(e)}

    def set_credentials(self, name: str, password: str) -> Dict[str, Any]:
        """Set Transkribus credentials."""
        try:
            set_credentials(name, password)
            return {"success": True, "output": "Credentials set successfully."}
        except Exception as e:
            return {"success": False, "output": str(e)}

    def show_settings(self) -> dict:
        """Show current Transkribus settings."""
        try:
            # This function prints to stdout, so we need to capture it.
            old_stdout = sys.stdout
            sys.stdout = captured_output = StringIO()
            show_settings()
            sys.stdout = old_stdout
            output = captured_output.getvalue()
            return {"success": True, "output": output}
        except Exception as e:
            return {"success": False, "output": str(e)}
