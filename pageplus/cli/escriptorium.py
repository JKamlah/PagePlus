import dataclasses
import json
import os
import re
import shutil
import tempfile
import zipfile
from datetime import datetime
from enum import Enum
from importlib import util
from io import BytesIO
from pathlib import Path
from shutil import rmtree
from typing import Dict, Tuple, Union, List

import typer
from rich import print
from rich.status import Status
from rich.table import Table
from typing_extensions import Annotated, Optional

app = typer.Typer()

if (spec := util.find_spec('escriptorium_connector')) is None:
    import subprocess
    import sys


    @app.command()
    def install() -> None:
        """
        Before escriptorium can be used, please use this install command
        to install escriptorium-connector by Bronson Brown-deVost!
        """
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-I", "escriptorium-connector"])

else:
    from escriptorium_connector import EscriptoriumConnector
    from dotenv import load_dotenv, find_dotenv, get_key, set_key, dotenv_values
    from escriptorium_connector.connector import TimeoutWebsocket
    import requests

    import logging

    logging.getLogger("requests").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)

    #### Here is some modified functions from eScriptorium Connector due to base_url subdirectory problems (e.g. base_url/escriptorium/) ###
    HttpUpload = Dict[str, Tuple[str, bytes]]


    # JSON dataclass support (See: https://stackoverflow.com/questions/51286748/make-the-python-json-encoder-support-pythons-new-dataclasses)
    class EnhancedJSONEncoder(json.JSONEncoder):
        def default(self, o):
            if dataclasses.is_dataclass(o):
                return dataclasses.asdict(o)
            return super().default(o)


    def post_url(
            escr,
            url: str,
            payload: dict,
            files: Union[HttpUpload, None] = None,
            as_form_data: bool = False, ) -> requests.Response:
        prepared_payload = json.loads(json.dumps(payload, cls=EnhancedJSONEncoder))
        return (
            escr.http.post(url, data=prepared_payload, files=files)
            if files is not None else (escr.http.post(url, data=prepared_payload)
                                       if as_form_data else escr.http.post(url, json=prepared_payload)
                                       )
        )


    def get_url(escr, url: str) -> requests.Response:
        return escr.http.get(url)


    def download_part_pagexml_transcription(escr, document_id, parts_id, transcription_id):
        if escr.cookie is None:
            raise Exception("Must use websockets to download PAGE-XML exports")

        download_link = None
        ws = (
            TimeoutWebsocket(sslopt={"cert_reqs": escr.CERT_NONE})
            if escr.http.verify is False
            else TimeoutWebsocket()
        )
        ws.connect(
            f"{escr.base_url.replace('http', 'ws')}ws/notif/",
            cookie=escr.cookie,
        )

        r = post_url(escr,
                     f"{escr.api_url}documents/{document_id}/export/",
                     {
                         "task": "export",
                         "csrfmiddlewaretoken": escr.csrfmiddlewaretoken,
                         "transcription": transcription_id,
                         "file_format": "pagexml",
                         "region_types": [
                                             x.pk for x in escr.get_document_region_types(document_id)
                                         ]
                                         + ["Undefined", "Orphan"],
                         "document": document_id,
                         "parts": parts_id,
                     },
                     as_form_data=True,
                     )
        message = ws.recv(120)
        ws.close()
        msg = json.loads(message)
        if "export" in msg["text"].lower():
            for entry in msg["links"]:
                if entry["text"].lower() == "download":
                    download_link = entry["src"]

        if download_link is None:
            print(
                f"Did not receive a link to download ALTO export for {document_id}, {parts_id}, {transcription_id}"
            )
            return None
        pagexml_request = get_url(escr, f"{escr.base_url.replace('/escriptorium', '')}{download_link}")

        if pagexml_request.status_code != 200:
            return None

        return pagexml_request.content


    def upload_part_transcription(
            escr,
            document_pk: int,
            transcription_name: str,
            filename: str,
            file_data: BytesIO,
            override: str = "off"):
        """Upload a PageXML

        Args:
            document_pk (int): Document PK
            transcription_name (str): Transcription name
            filename (str): Filename
            file_data (BytesIO): File data as a BytesIO
            override (str): Whether to override existing segmentation data ("on") or not ("off", default)

        Returns:
            null: Nothing
        """

        request_payload = {"task": "import-xml", "name": transcription_name}
        if override == "on":
            request_payload["override"] = "on"

        return post_url(escr,
                        f"{escr.api_url}documents/{document_pk}/imports/",
                        request_payload,
                        {"upload_file": (filename, file_data)},
                        )


    @app.command()
    def set_url(url: str) -> None:
        """
        Write the URL of the eScritpriums instance (e.g. https://www.escriptorium.fr) to the .env file
        Returns:
        None
        """
        dotfile = find_dotenv()
        set_key(dotfile, "ESCRIPTORIUM_URL", url)


    @app.command()
    def set_credentials(name: str, password: str) -> None:
        """
        Write your credentials to the .env file
        Returns:
        None
        """
        dotfile = find_dotenv()
        set_key(dotfile, "ESCRIPTORIUM_USERNAME", name)
        set_key(dotfile, "ESCRIPTORIUM_PASSWORD", password)


    @app.command()
    def show_envs() -> None:
        """
        Print your current credentials from the .env file
        Returns:
        None
        """
        table = Table(title="eScriptorium's environment variables")
        table.add_column("Environment variable name", justify="right", style="cyan", no_wrap=True)
        table.add_column("Environment variable value")
        [table.add_row(var, key) for (var, key) in dotenv_values().items() if "escriptorium" in var.lower()]
        print(table)


    class DocumentFilterOptions(str, Enum):
        """
        Filter options for eScriptorium documents
        """
        project = "project"
        document = "document"
        transcription = "transcription"


    @app.command()
    def find_documents(filter_by: Annotated[DocumentFilterOptions, typer.Option(
        help="Choose the reading order mode auto (try reading order group than document), reading-order-group (only) or document (only)",
        case_sensitive=False)],
                       search_term: Annotated[
                           Optional[str], typer.Option(
                               help="RegEx search term for the filter option (Use . to find all documents)")],
                       case_sensitive: Annotated[Optional[bool], typer.Option(
                           help="RegEx search term for the filter option")] = False) -> None:
        """
        Print your project, document (documentID), pages, transcription (transcriptionID)
        Returns:
        None
        """
        load_dotenv()
        envs = dotenv_values()
        escr = EscriptoriumConnector(envs['ESCRIPTORIUM_URL'],
                                     envs['ESCRIPTORIUM_USERNAME'],
                                     envs['ESCRIPTORIUM_PASSWORD'])

        with Status("Searching for documents") as status:
            documents = escr.get_documents()

        print(f"[bold green]eScriptorium Document Search Report[/bold green] - [white]Version 1.0[/white]")
        print(f"Total documents found: {documents.count}")
        count = documents.count
        flag = 0 if case_sensitive else re.IGNORECASE
        if filter_by is not None:
            for idx, document in enumerate(documents.results[::-1]):
                if not ((filter_by == "project" and re.match(search_term, document.project, flags=flag)) or
                        (filter_by == "document" and re.match(search_term, document.name, flags=flag)) or
                        (filter_by == "transcription" and any(
                            [re.match(search_term, trans.name, flags=flag) for trans in document.transcriptions]))):
                    del documents.results[count - 1 - idx]
            print(f"Documents meeting filter criteria: {len(documents.results)}")
        table = Table(title="")
        table.add_column("Project", style="green")
        table.add_column("Document (ID)", style="cyan")
        table.add_column("Pages", style="blue")
        table.add_column("Transcription (ID)", style="steel_blue3")
        for document in documents.results:
            table.add_row(document.project,
                          f"{document.name} ({document.pk})",
                          f"{document.parts_count}",
                          '\n'.join([f"{trans.name} ({trans.pk})" for trans in document.transcriptions]))
        print(table)


    @app.command()
    def load_document(document_pk: int, pages: List[int], transcription_pk: int,
                      foldername: str = "DATAFOLDER") -> None:
        """
        Loads pages of a document to work with PagePlus
        Returns:
        None
        """
        # Create a Path object for the directory
        load_dotenv()
        envs = dotenv_values()
        escr = EscriptoriumConnector(envs['ESCRIPTORIUM_URL'],
                                     envs['ESCRIPTORIUM_USERNAME'],
                                     envs['ESCRIPTORIUM_PASSWORD'])
        parts_pk = [part.pk for idx, part in enumerate(escr.get_document_parts(document_pk).results) if idx in pages]
        zipped_pagexmls_binary = escr.download_part_pagexml_transcription(document_pk, parts_pk, transcription_pk)
        zipped_pagexmls = zipfile.ZipFile(BytesIO(zipped_pagexmls_binary))
        datafolder = Path(tempfile.mkdtemp(prefix="PagePlus_"))
        dotfile = find_dotenv()
        with open(datafolder.joinpath('metadata_pageplus.json'), 'w') as meta:
            json.dump({'document_pk': document_pk,
                       'parts_pk': parts_pk,
                       'transcription_pk': transcription_pk,
                       'downloaded at': datetime.now().strftime('%H_%M_%d_%m_%Y'),
                       'downloaded from': get_key(dotfile, 'ESCRIPTORIUM_URL'),
                       'downloaded by': get_key(dotfile, 'ESCRIPTORIUM_USERNAME')},
                      meta, indent=4)

        zipped_pagexmls.extractall(datafolder)

        foldername = "ESCRIPTORIUM_" + foldername.upper()
        current_folder = get_key(dotfile, foldername)
        if current_folder is not None and current_folder != '' and Path(current_folder).exists():
            rmtree(current_folder)
        set_key(dotfile, foldername, str(datafolder))


    class DatafolderType(str, Enum):
        """
        Filter options for eScriptorium documents
        """
        original = "original"
        modified = "modified"


    @app.command()
    def update_document(
            use_current_dataset: bool = True,
            datafoldertype: Annotated[
                DatafolderType, typer.Option(help="Choose document (only)", case_sensitive=False)] = 'modified',
            datapath: Annotated[
                Path, typer.Option(help="Path to the xml file directory (only if not current-dataset is used)")] = None,
            document_pk: int = None, transcription_pk: int = None, transcription_name: str = None,
            overwrite: bool = True) -> None:
        """
        Uploads pages of a document to eScriptorium
        Returns:
        None
        """
        load_dotenv()
        envs = dotenv_values()
        escr = EscriptoriumConnector(envs['ESCRIPTORIUM_URL'],
                                     envs['ESCRIPTORIUM_USERNAME'],
                                     envs['ESCRIPTORIUM_PASSWORD'])
        overwrite = {True: "on", False: "off"}.get(overwrite)

        # Create a BytesIO object to hold the zip file in memory
        file_data = BytesIO()

        if use_current_dataset:
            datafolder = Path(envs['ESCRIPTORIUM_DATAFOLDER'])
            metadata = json.loads(datafolder.joinpath('metadata_pageplus.json').open('r').read())
            document_pk = metadata.get('document_pk', None)
            transcription_pk = metadata.get('transcription_pk', None)
            datafolder = datafolder.joinpath({'original': '', 'modified': 'PagePlusOutput'}.get(datafoldertype))
        elif datapath is not None:
            datafolder = Path(datapath)
        else:
            return
        if transcription_name is None and transcription_pk is not None:
            transcription_name = escr.get_document_transcription(document_pk, transcription_pk).name
        if transcription_name is None:
            return
        if not datafolder.exists() or document_pk is None or transcription_name is None:
            return
        # Create a ZipFile object with the BytesIO object as file, in write mode
        with zipfile.ZipFile(file_data, 'w', zipfile.ZIP_DEFLATED) as zip_file:
            # Recursively add files to the zip file
            [zip_file.write(file) for file in datafolder.glob('*.xml') if
             file.is_file() and file.name.lower not in ['metadata.xml', 'mets.xml']]
        # Check if we have data to update
        file_data.seek(0, 2)
        if file_data.tell() == 0:
            return
        # Reset the pointer to the beginning of the BytesIO object
        file_data.seek(0, 0)

        # Update transcription in eS
        escr.upload_part_transcription(document_pk, transcription_name, transcription_name + '.zip', file_data,
                                       override=overwrite)


    @app.command()
    def export_document(
            datafolder: Annotated[DatafolderType, typer.Option(help="Choose document (only)", case_sensitive=False)],
            outputdir: Annotated[
                Path, typer.Option(help="Path to the output directory where the text files will be saved")]) -> None:
        """
        Loads pages of a document to work with PagePlus
        Returns:
        None
        """
        datafolder = Path(get_key(find_dotenv(), 'ESCRIPTORIUM_DATAFOLDER')).joinpath(
            {'original': '', 'modified': 'PagePlusOutput'}.get(datafolder))
        Path(outputdir).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(datafolder, outputdir)


    @app.command()
    def open_datafolder() -> None:
        """
        Open a folder in the file explorer, works for Windows, macOS, and Linux.
        """
        datafolder = get_key(find_dotenv(), "ESCRIPTORIUM_DATAFOLDER")
        if datafolder == '':
            return
        if sys.platform == "win32":
            # Windows
            os.startfile(datafolder)
        elif sys.platform == "darwin":
            # macOS
            subprocess.run(["open", datafolder])
        else:
            # Linux and other Unix-like OS
            subprocess.run(["xdg-open", datafolder])

if __name__ == "__main__":
    app()
