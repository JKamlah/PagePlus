from pageplus.cli.escriptorium import (
    set_base_url,
    set_api_base_url,
    set_instance_name,
    set_credentials,
    show_settings,
    find_documents,
    load_document,
    update_document,
    set_document_pk,
    set_transcription_pk,
    install
)
from typing import List, Optional
from io import StringIO
import sys
from pageplus.gui.cli_bridges.base import CLIBridge, capture_output


class EscriptoriumBridge(CLIBridge):
    """Bridge for eScriptorium CLI operations."""

    def install(self) -> dict:
        """Install the eScriptorium connector."""
        try:
            output = capture_output(install)
            return {"success": True, "output": output}
        except Exception as e:
            return {"success": False, "output": str(e)}

    def set_base_url(self, base_url: str) -> dict:
        """Set the base URL for eScriptorium."""
        try:
            set_base_url(base_url)
            return {"success": True, "output": "Base URL set successfully."}
        except Exception as e:
            return {"success": False, "output": str(e)}

    def set_api_base_url(self, base_url: str) -> dict:
        """Set the API base URL for eScriptorium."""
        try:
            set_api_base_url(base_url)
            return {"success": True, "output": "API Base URL set successfully."}
        except Exception as e:
            return {"success": False, "output": str(e)}

    def set_instance_name(self, instance_name: str) -> dict:
        """Set the instance name for eScriptorium."""
        try:
            set_instance_name(instance_name)
            return {"success": True, "output": "Instance name set successfully."}
        except Exception as e:
            return {"success": False, "output": str(e)}

    def set_credentials(self, name: str, password: str) -> dict:
        """Set credentials for eScriptorium."""
        try:
            set_credentials(name, password)
            return {"success": True, "output": "Credentials set successfully."}
        except Exception as e:
            return {"success": False, "output": str(e)}

    def show_settings(self) -> dict:
        """Show current eScriptorium settings."""
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

    def set_document_pk(self, pk: int) -> dict:
        """Set the document PK for eScriptorium."""
        try:
            if pk:
                set_document_pk(pk)
                return {"success": True, "output": f"Document PK set to {pk}."}
            return {"success": False, "output": "No Document PK provided."}
        except Exception as e:
            return {"success": False, "output": str(e)}

    def set_transcription_pk(self, pk: int) -> dict:
        """Set the transcription PK for eScriptorium."""
        try:
            if pk:
                set_transcription_pk(pk)
                return {"success": True, "output": f"Transcription PK set to {pk}."}
            return {"success": False, "output": "No Transcription PK provided."}
        except Exception as e:
            return {"success": False, "output": str(e)}

    def find_documents(self, filter_by: List[str], search_term: List[str], case_sensitive: bool) -> dict:
        """Find documents in eScriptorium."""
        try:
            old_stdout = sys.stdout
            sys.stdout = captured_output = StringIO()

            table = find_documents(filter_by, search_term, case_sensitive)

            sys.stdout = old_stdout
            output = captured_output.getvalue()
            return {"success": True, "output": output, "table": table}
        except Exception as e:
            return {"success": False, "output": str(e)}

    def load_document(self, document_pk: int, transcription_pk: int, pages: Optional[List[str]] = None,
                      load_images: bool = False, folderpath: Optional[str] = None, workspace: str = "MAIN",
                      overwrite_ws: bool = False, loading: bool = True) -> dict:
        """Load a document from eScriptorium."""
        try:
            old_stdout = sys.stdout
            sys.stdout = captured_output = StringIO()

            load_document(document_pk, transcription_pk, pages, load_images, folderpath, workspace, overwrite_ws, loading)

            sys.stdout = old_stdout
            output = captured_output.getvalue()
            return {"success": True, "output": output}
        except Exception as e:
            return {"success": False, "output": str(e)}

    def update_document(self, inputs: List[str], document_pk: Optional[int] = None,
                        pages: Optional[List[str]] = None,
                        transcription_name: Optional[str] = None, overwrite: bool = True) -> dict:
        """Update a document in eScriptorium."""
        try:
            old_stdout = sys.stdout
            sys.stdout = captured_output = StringIO()

            update_document(inputs, document_pk, pages, transcription_name, overwrite)

            sys.stdout = old_stdout
            output = captured_output.getvalue()
            return {"success": True, "output": output}
        except Exception as e:
            return {"success": False, "output": str(e)}
