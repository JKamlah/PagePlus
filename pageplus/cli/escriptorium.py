import logging
import json
import re
import subprocess
import sys
import tempfile
import zipfile
from datetime import datetime
from enum import Enum
from importlib import util
from io import BytesIO
from pathlib import Path
from shutil import rmtree
from typing import List

import pandas as pd
import typer
from rich import print
from rich.status import Status
from rich.table import Table
from typing_extensions import Annotated, Optional

app = typer.Typer()


if (spec := util.find_spec('escriptorium_connector')) is None:

    @app.command()
    def install() -> None:
        """
        Before escriptorium can be used, please use this install command
        to install escriptorium-connector by Bronson Brown-deVost!
        """
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "-I", "git+https://github.com/JKamlah/escriptorium_python_connector.git"])

else:
    from escriptorium_connector import EscriptoriumConnector
    from dotenv import load_dotenv, find_dotenv, set_key, dotenv_values

    from pageplus.utils.constants import Environments, Bool2OnOff
    from pageplus.utils.envs import str_to_env
    from pageplus.utils.workspace import Workspace
    from pageplus.utils.api import EscriptoriumAPI
    from pageplus.utils.fs import transform_inputs, collect_xml_files
    from pageplus.utils.converter import parse_page_ranges

    es_workspace = Workspace(Environments.PAGEPLUS)
    es_api = EscriptoriumAPI(Environments.ESCRIPTORIUM)

    # PACKAGE #
    @app.command(rich_help_panel="Package")
    def install() -> None:
        """
        Updates PagePlus-transkribus-utils based on acdh-transkribus-utils
        by Peter Andorfer, Matthias Schlögl, Carl Friedrich Haak!
        """
        """
        Updates escriptorium-connector by Bronson Brown-deVost!
        """
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "-I", "git+https://github.com/JKamlah/escriptorium_python_connector.git"])

    # CONSTANTS #
    class DataFilter(str, Enum):
        """
        Filter options of the data for eScriptorium
        """
        PROJECT = "Project"
        DOCUMENT = "Document"
        TRANSCRIPTION = "Transcription"

    class DataLevel(str, Enum):
        """
        Level of escriptorium data
        """
        PROJECT = "Project"
        DOCUMENT = "Document"
        PAGE = "Page"

    # SETTINGS #
    @app.command(rich_help_panel="Settings")
    def set_base_url(base_url: Annotated[str, typer.Argument(
            help="URL to eScriptorium")]) -> None:
        """
        Write the URL of the eScriptorium instance if it not refers to the official url
        https://transkribus.eu/TrpServer/rest to the .env file
        Returns:
        None
        """
        es_api.base_url = base_url

    @app.command(rich_help_panel="Settings")
    def set_api_base_url(base_url: Annotated[str, typer.Argument(
            help="URL to eScriptorium API")]) -> None:
        """
        Write the URL of the eScriptorium API instance to the .env file
        Returns:
        None
        """
        es_api.api_base_url = base_url

    @app.command(rich_help_panel="Settings")
    def set_instance_name(instance_name: Annotated[str, typer.Argument(
            help="URL to Transkribus")]) -> None:
        """
        Set the instance name of the eScriptorium instance
        Returns:
        None
        """
        es_api.instance_name = instance_name

    @app.command(rich_help_panel="Settings")
    def set_credentials(name: Annotated[str,
                                        typer.Argument(help="Username for Transkribus")],
                        password: Annotated[str,
                        typer.Argument(help="Password for Transkribus")]) -> None:
        """
        Write your credentials to the .env file
        Returns:
        None
        """
        es_api.credentials = (name, password)

    @app.command(rich_help_panel="Settings")
    def set_document_pk(document_pk: Annotated[int, typer.Argument(
            help="Document pk")]) -> None:
        """
        Set the document pk for eScriptorium
        Returns:
        None
        """
        es_api.document_pk = document_pk
    
    @app.command(rich_help_panel="Settings")
    def set_transcription_pk(transcription_pk: Annotated[int, typer.Argument(
            help="Transcription pk")]) -> None:
        """
        Set the transcription pk for eScriptorium
        Returns:
        None
        """
        es_api.transcription_pk = transcription_pk

    @app.command(rich_help_panel="Settings")
    def show_settings() -> None:
        """
        Print your current settings from the .env file
        Returns:
        None
        """
        es_api.show_settings()

    # DOCUMENTS #
    @app.command(rich_help_panel="Document")
    def find_documents(filter_by: Annotated[List[DataFilter], typer.Option("--filter-by", "-f",
                                                                           help="Filter the document search by "
                                                                           "the name of the 'project', "
                                                                           "'document' or 'transcription'",
                                                                           case_sensitive=False)],
                       search_term: Annotated[List[str], typer.Option("--search-term", "-s",
                                                                      help="RegEx search term for the filter option (Use . to find "
                                                                      "all documents)")],
                       case_sensitive: Annotated[Optional[bool], typer.Option(
                           help="De-/Activate case sensitivity for the regex search")] = False) -> None:
        """
        Print your project, document (documentPK), pages, transcription (transcriptionPK)
        Returns:
        None
        """
        load_dotenv()
        if not es_api.valid_login():
            return
        escr = EscriptoriumConnector(
            es_api.base_url,
            *es_api.credentials,
            es_api.api_key,
            es_api.api_base_url,
            instance_name=es_api.instance_name)
        if len(filter_by) != len(search_term):
            print("Please provide for each filter a search term")
            return
        with Status("Searching for documents"):
            try:
                documents = escr.get_documents()
            except BaseException:
                print("[red]Missing login information: Ensure that the URL, username, and password or "
                      "API URL and key are correctly configured.[/red]")
                return
        print("[bold green]eScriptorium Document Search Report[/bold green] - [white]Version 1.0[/white]")
        print(f"Total documents found: {documents.count}")
        count = documents.count
        flag = 0 if case_sensitive else re.IGNORECASE
        if filter_by is not None:
            for idx, document in enumerate(documents.results[::-1]):
                print(document)
                for f, s in zip(filter_by, search_term):
                    if not (
                        (f == "Project" and re.match(
                            s,
                            document.project,
                            flags=flag)) or (
                            f == "Document" and re.match(
                                s,
                                document.name,
                                flags=flag)) or (
                            f == "Transcription" and any(
                                [
                            re.match(
                                s,
                                trans.name,
                                flags=flag) for trans in document.transcriptions]))):
                        del documents.results[count - 1 - idx]
                        break
            print(f"Documents meeting filter criteria: {len(documents.results)}")
        table = Table(title="")
        table.add_column("Project", style="green")
        table.add_column("Document (PK)", style="cyan")
        table.add_column("Pages", style="blue")
        table.add_column("Transcription (PK)", style="steel_blue3")
        for document in documents.results:
            table.add_row(document.project,
                          f"{document.name} ({document.pk})",
                          f"{document.parts_count}",
                          '\n'.join([f"{trans.name} ({trans.pk})" for trans in document.transcriptions]))
        print(table)

        # Create a pandas DataFrame from the results
        data = {
            "Project": [doc.project for doc in documents.results],
            "Document (PK)": [f"{doc.name} ({doc.pk})" for doc in documents.results],
            "Pages": [doc.parts_count for doc in documents.results],
            "Transcription (PK)": [
                [f"{trans.name} ({trans.pk})" for trans in doc.transcriptions] for doc in documents.results
            ]
        }
        df = pd.DataFrame(data)

        return df

    @app.command(rich_help_panel="Document")
    def load_document(document_pk: Annotated[int,
                                             typer.Argument(help="Document's primary key (pk).")],
                      transcription_pk: Annotated[int,
                                                  typer.Argument(help="Transcription's primary key (pk).")],
                      pages: Annotated[Optional[List[str]],
                                       typer.Option("--pages",
                                                    "-p",
                                                    help="Page selection (e.g., '5' or '10-13'). "
                                                         "If not set all pages get loaded.")] = None,
                      load_images: Annotated[bool,
                                             typer.Option(help="Store also the corresponding images")] = False,
                      folderpath: Annotated[Optional[Path],
                                            typer.Option("--folderpath",
                                                         "-f",
                                                         help="Path to store the loaded document. If "
                                                         "not set it get stored in the workspace "
                                                         "directory.")] = None,
                      workspace: Annotated[Optional[str],
                                           typer.Option("--workspace",
                                                        "-w",
                                                        help="Name of environmental variable, which "
                                                        "stores the path to loaded document. The "
                                                        "name get's appended to 'ESCRIPTORIUM_WS_' and "
                                                        "automatically cast to uppercase. E.g. "
                                                        "new data -> ESCRIPTORIUM_WS_NEW_DATA.")] = None,
                      overwrite_ws: Annotated[bool,
                                              typer.Option(help="If workspace already exists the old data gets removed.")] = False,
                      loading: Annotated[bool,
                                         typer.Option(help="Load the created workspace as default")] = True) -> None:
        """
        Loads pages of a document with a specific transcription to work with PagePlus.
        For more information abouth the pk values and page numbers see the --find-documents function.
        Returns:
        None
        """
        # Create a Path object for the directory
        load_dotenv()
        envs = dotenv_values()
        workspace = workspace if workspace is not None else ""
        if workspace != "":
            workspace = str_to_env(workspace)
        if not es_api.valid_login():
            return
        escr = EscriptoriumConnector(
            es_api.base_url,
            *es_api.credentials,
            es_api.api_key,
            es_api.api_base_url,
            instance_name=es_api.instance_name)

        parts_to_load = parse_page_ranges(pages)
        document_parts = escr.get_document_parts(document_pk).results

        # Filter parts based on page selection
        if parts_to_load:
            document_parts = [p for idx, p in enumerate(document_parts) if idx + 1 in parts_to_load]

        parts_pk = [part.pk for part in document_parts]

        with Status("Downloading transcription"):
            zipped_pagexmls_binary = escr.download_part_pagexml_transcription(
                document_pk, parts_pk, transcription_pk)
        zipped_pagexmls = zipfile.ZipFile(
            BytesIO(zipped_pagexmls_binary)) if zipped_pagexmls_binary else None

        wsfolder = Path(
            tempfile.mkdtemp(
                prefix=es_workspace.prefix_dir(),
                dir=es_workspace.dir())) if folderpath is None else Path(folderpath)
        wsfolder.mkdir(parents=True, exist_ok=True)

        if load_images:
            with Status("Downloading images"):
                for part in document_parts:
                    print(f"{escr.base_url}{part.image.uri}".replace(
                        'escriptorium/escriptorium', 'escriptorium'))
                    r = escr.http.get(f"{escr.base_url}{part.image.uri.lstrip('/')}"
                                      .replace('escriptorium/escriptorium', 'escriptorium'))
                    image = r.content
                    wsfolder.joinpath(part.filename).open('wb').write(image)

        # Load additional information
        # project_information = escr.get_projects()
        # TODO: Find project name and/or id
        metadata = {
            es_workspace.env: {
                'project': {
                    'document': {
                        'document_pk': document_pk,
                        'transcription_pk': transcription_pk,
                        'downloaded at': datetime.now().strftime('%H_%M_%d_%m_%Y'),
                        'downloaded from': envs.get(
                            es_workspace.prefix +
                            'URL',
                            ''),
                        'downloaded by': envs.get(
                            es_workspace.prefix +
                            'USERNAME',
                            ''),
                        'page': [{'pk': doc.pk, 'filename': doc.filename, 'name': doc.name, 'title': doc.title} for doc in document_parts]}}}}

        with open(wsfolder.joinpath('metadata.pageplus.json'), 'w') as meta:
            json.dump(metadata, meta, indent=4)

        if zipped_pagexmls_binary:
            zipped_pagexmls.extractall(wsfolder)

        ws_absolute = es_workspace.prefix_ws + workspace
        current_folder = envs.get(ws_absolute, '')
        if current_folder is not None and current_folder != '' and Path(
                current_folder).exists():
            if overwrite_ws:
                rmtree(current_folder)
            else:
                print(f"The data in folder {Path(current_folder).absolute()} is now unset. "
                      f"You can load it with the load local documents function.")
        if workspace != "":
            set_key(find_dotenv(), ws_absolute, str(wsfolder.absolute()))
            if loading:
                es_workspace.load(workspace)
        print(f"The data was successfully stored in: [bold purple]{str(wsfolder.absolute())}[/bold purple]")
        print(f"And be access via the eScriptorium workspace: [bold green]{workspace}[/bold green]")

    @app.command(rich_help_panel="Document")
    def update_document(
            inputs: Annotated[List[str], typer.Argument(exists=True, help="Paths to the XML files to be checked.", callback=transform_inputs)] = None,
            document_pk: Annotated[int, typer.Option("--document-pk", "-d",
                                                     help="Document's primary key (pk). (Not necessary if "
                                                          "environmental is used, but can also overwrite)")] = None,
            pages: Annotated[Optional[List[str]], typer.Option("--pages", "-p",
                                                               help="Page selection (e.g., '5' or '10-13'). "
                                                               "If not set all pages get uploaded.")] = None,
            transcription_name: Annotated[str, typer.Option("--transcription-name", "-n",
                                                            help="Transcription's name. Overwrites transcription pk! "
                                                                 "(Not necessary if environmental is used, "
                                                                 "but can also overwrite)")] = None,
            overwrite: Annotated[bool, typer.Option(help="Overwrite existing Transcription")] = True) -> None:
        """
        Uploads pages of a document to eScriptorium.
        Returns:
        None
        """
        load_dotenv()
        envs = dotenv_values()

        if not es_api.valid_login():
            return

        escr = EscriptoriumConnector(
            es_api.base_url,
            *es_api.credentials,
            es_api.api_key,
            es_api.api_base_url,
            instance_name=es_api.instance_name)
        overwrite = Bool2OnOff.get(overwrite)

        # Create a BytesIO object to hold the zip file in memory
        file_data = BytesIO()
        xml_files = collect_xml_files(map(Path, inputs))
        # Raise error if no xml files are found
        if not xml_files:
            raise FileNotFoundError('No xml files found in input directory')
        
        parts_to_update = parse_page_ranges(pages)

        all_parts = escr.get_document_parts(document_pk).results
        if parts_to_update:
            document_parts = [p for idx, p in enumerate(all_parts) if idx + 1 in parts_to_update]
            parts_filename = [Path(part.filename).with_suffix('.xml') for part in document_parts]
            parts_to_upload = [xml_file for xml_file in xml_files if xml_file.name in parts_filename]
        else:
            parts_to_upload = xml_files

        # Create a ZipFile object with the BytesIO object as file, in write
        # mode
        with zipfile.ZipFile(file_data, 'w', zipfile.ZIP_DEFLATED) as zip_file:
            # Recursively add files to the zip file
            [zip_file.write(file) for file in parts_to_upload if file.exists()]
        # Check if we have data to update
        file_data.seek(0, 2)
        if file_data.tell() == 0:
            return
        # Reset the pointer to the beginning of the BytesIO object
        file_data.seek(0, 0)

        # Update transcription in eS
        with Status("Updating document"):
            escr.upload_part_transcription(
                document_pk,
                transcription_name,
                transcription_name + '.zip',
                file_data,
                override=overwrite)
        logging.info("Updating completed!")


if __name__ == "__main__":
    app()
