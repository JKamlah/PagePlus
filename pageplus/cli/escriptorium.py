import dataclasses
import json
import os
import re
import shutil
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
from typing import Dict, Tuple, Union, List

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
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-I", "escriptorium-connector"])

else:
    from escriptorium_connector import EscriptoriumConnector
    from dotenv import load_dotenv, find_dotenv, get_key, set_key, dotenv_values
    import logging

    logging.getLogger("requests").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)


    ES_PREFIX = "ESCRIPTORIUM_"
    class DocumentFilterOptions(str, Enum):
        """
        Filter options for eScriptorium documents
        """
        project = "project"
        document = "document"
        transcription = "transcription"


    class DataState(str, Enum):
        """
        State of the data
        """
        original = "original"
        modified = "modified"


    @app.command()
    def set_url(url: Annotated[str, typer.Argument(help="URL to eScriptorium")]) -> None:
        """
        Write the URL of the eScritpriums instance (e.g. https://www.escriptorium.fr) to the .env file
        Returns:
        None
        """
        dotfile = find_dotenv()
        set_key(dotfile, ES_PREFIX+"URL", url)

    @app.command()
    def set_credentials(name: Annotated[str, typer.Argument(help="Username for eScriptorium")],
                        password: Annotated[str, typer.Argument(help="Password for eScriptorium")]) -> None:
        """
        Write your credentials to the .env file
        Returns:
        None
        """
        dotfile = find_dotenv()
        set_key(dotfile, ES_PREFIX+"USERNAME", name)
        set_key(dotfile, ES_PREFIX+"PASSWORD", password)

    @app.command()
    def set_api_url(url: Annotated[str, typer.Argument(help="API url for eScriptorium")]) -> None:
        """
        Set if api url differs from base-url/api and api-key should be used
        WARNING: Currently
        Returns:
        None
        """
        dotfile = find_dotenv()
        set_key(dotfile, ES_PREFIX+"API_URL", url)


    @app.command()
    def set_api_key(key: Annotated[str, typer.Argument(help="API key for eScriptorium")],
                    force: Annotated[bool, typer.Option(help="Force to set the API key")] = False) -> None:
        """
        Set the API key for eScriptorium (only used if name and password is not set).
        Returns:
        None
        """
        dotfile = find_dotenv()
        if not force:
            print(f"DISCLAIMER: Please don't use this method currently for the instance of UB-Mannheim."
                  f"Since there currently some problems. You can anyways still set the API-Key with the force flag.")
        else:
            set_key(dotfile, ES_PREFIX+"API_KEY", key)


    @app.command()
    def valid_login() -> bool:
        envs = dotenv_values()
        check = all([envs.get(ES_PREFIX+'URL', None), envs.get(ES_PREFIX+'USERNAME', None), envs.get(ES_PREFIX+'PASSWORD', None)])
        check_api = all([envs.get(ES_PREFIX+'API_KEY', None), any([envs.get(ES_PREFIX+'URL', None), envs.get(ES_PREFIX+'API_URL', None)])])
        if not check and not check_api:
            print(f"Missing login information: Ensure that the URL, username, and password or "
                  f"API URL and key are correctly configured.")
            return False
        return True

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
        [table.add_row(var, key) if "password" not in var.lower() else table.add_row(var, key[:3] + '***') for
         (var, key) in dotenv_values().items() if "escriptorium" in var.lower()]
        print(table)


    @app.command()
    def find_documents(filter_by: Annotated[DocumentFilterOptions, typer.Option("--filter-by", "-f",
                                                                                help="Filter the document search by "
                                                                                     "the name of the 'project', "
                                                                                     "'document' or 'transcription'",
                                                                                case_sensitive=False)] = 'document',
                       search_term: Annotated[
                           Optional[str], typer.Option("--search-term", "-s",
                                                       help="RegEx search term for the filter option (Use . to find "
                                                            "all documents)")] = '.',
                       case_sensitive: Annotated[Optional[bool], typer.Option(
                           help="De-/Activate case sensitivity for the regex search")] = False) -> None:
        """
        Print your project, document (documentPK), pages, transcription (transcriptionPK)
        Returns:
        None
        """
        load_dotenv()
        envs = dotenv_values()
        if not valid_login():
            return
        escr = EscriptoriumConnector(envs.get(ES_PREFIX+'URL', None),
                                     envs.get(ES_PREFIX+'USERNAME', None),
                                     envs.get(ES_PREFIX+'PASSWORD', None),
                                     envs.get(ES_PREFIX+'API_KEY', None),
                                     envs.get(ES_PREFIX+'API_URL', None))

        with Status("Searching for documents") as status:
            try:
                documents = escr.get_documents()
            except:
                print(f"Missing login information: Ensure that the URL, username, and password or "
                  f"API URL and key are correctly configured.")
                return

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
        table.add_column("Document (PK)", style="cyan")
        table.add_column("Pages", style="blue")
        table.add_column("Transcription (PK)", style="steel_blue3")
        for document in documents.results:
            table.add_row(document.project,
                          f"{document.name} ({document.pk})",
                          f"{document.parts_count}",
                          '\n'.join([f"{trans.name} ({trans.pk})" for trans in document.transcriptions]))
        print(table)


    @app.command()
    def load_document(document_pk: Annotated[int,
                      typer.Argument(help="Document's primary key (pk).")],
                      transcription_pk: Annotated[int,
                      typer.Argument(help="Transcription's primary key (pk).")],
                      pages: Annotated[Optional[List[int]],
                      typer.Option("--pages", "-p",
                                   help="Page selection. If not set all pages get loaded.")] = None,
                      folderpath: Annotated[Optional[Path], typer.Option("--folderpath", "-f",
                                                                         help="Path to store the loaded document. If "
                                                                              "not set it get stored in a temporary "
                                                                              "folder.")] = None,
                      envname: Annotated[Optional[str], typer.Option("--envname", "-e",
                                                                     help="Name of enviormental variable, which "
                                                                          "stores the path to loaded document. The "
                                                                          "name get's appended to 'ESCRIPTORIUM_' and "
                                                                          "automatically cast to uppercase. E.g. "
                                                                          "new_data -> ESCRIPTORIUM_NEW_DATA.")] =
                      "DATAFOLDER") -> None:
        """
        Loads pages of a document with a specific transcription to work with PagePlus.
        For more information abouth the pk values and page numbers see the --find-documents function.
        Returns:
        None
        """
        # Create a Path object for the directory
        load_dotenv()
        envs = dotenv_values()
        if not valid_login():
            return
        escr = EscriptoriumConnector(envs.get(ES_PREFIX+'URL', None),
                                     envs.get(ES_PREFIX+'USERNAME', None),
                                     envs.get(ES_PREFIX+'PASSWORD', None),
                                     envs.get(ES_PREFIX+'API_KEY', None),
                                     envs.get(ES_PREFIX+'API_URL', None))

        parts_pk = [part.pk for idx, part in enumerate(escr.get_document_parts(document_pk).results) if
                    not pages or (idx + 1 in pages)]

        with Status("Downloading documents") as status:
            zipped_pagexmls_binary = escr.download_part_pagexml_transcription(document_pk, parts_pk, transcription_pk)

        zipped_pagexmls = zipfile.ZipFile(BytesIO(zipped_pagexmls_binary))

        datafolder = Path(tempfile.mkdtemp(prefix="PagePlus_")) if folderpath is None else Path(folderpath)
        datafolder.mkdir(parents=True, exist_ok=True)

        dotfile = find_dotenv()

        with open(datafolder.joinpath('metadata_pageplus.json'), 'w') as meta:
            json.dump({'document_pk': document_pk,
                       'parts_pk': parts_pk,
                       'transcription_pk': transcription_pk,
                       'downloaded at': datetime.now().strftime('%H_%M_%d_%m_%Y'),
                       'downloaded from': get_key(dotfile, ES_PREFIX+'URL'),
                       'downloaded by': get_key(dotfile, ES_PREFIX+'USERNAME')},
                      meta, indent=4)

        zipped_pagexmls.extractall(datafolder)

        foldername = ES_PREFIX + envname.upper()
        current_folder = get_key(dotfile, foldername)
        if current_folder is not None and current_folder != '' and Path(current_folder).exists():
            rmtree(current_folder)
        set_key(dotfile, foldername, str(datafolder))
        print(f"The data was successfully stored in {str(datafolder)}")
        print(f"And be access via [bold green]{foldername}[/bold green]")

    @app.command()
    def update_document(
            datafolder: Annotated[
                str, typer.Option('--datafolder', '-f',
                                  help="A path or an environmental name pointing to an existing path")] = "DATAFOLDER",
            datastate: Annotated[Optional[DataState], typer.Option('--datastate', '-s',
                                                                   help="Choose the documents inside this folder with "
                                                                        "'original', or the 'modified' scripts inside "
                                                                        "the subfolder (PagePlusOutput).",
                                                                   case_sensitive=False)] = "original",
            document_pk: Annotated[int, typer.Option("--document-pk", "-d",
                                                     help="Document's primary key (pk). (Not necessary if "
                                                          "environmental is used, but can also overwrite)")] = None,
            transcription_pk: Annotated[int, typer.Option("--transcription-pk", "-t",
                                                          help="Transcription's primary key (pk). (Not necessary if "
                                                               "environmental is used, but can also overwrite)")] =
            None,
            pages: Annotated[Optional[List[int]], typer.Option("--pages", "-p",
                                                               help="Page selection. If not set all pages get uploaded.")] = None,
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
        escr = EscriptoriumConnector(envs[ES_PREFIX+'URL'],
                                     envs[ES_PREFIX+'USERNAME'],
                                     envs[ES_PREFIX+'PASSWORD'])
        overwrite = {True: "on", False: "off"}.get(overwrite)

        # Create a BytesIO object to hold the zip file in memory
        file_data = BytesIO()
        if ES_PREFIX + datafolder.upper() in envs['ESCRIPTORIUM']:
            datafolder = Path(envs[ES_PREFIX + datafolder.upper()])
            metadata = json.loads(datafolder.joinpath('metadata_pageplus.json').open('r').read())
            document_pk = metadata.get('document_pk', None) if document_pk is None else document_pk
            transcription_pk = metadata.get('transcription_pk', None) if transcription_pk is None else transcription_pk
            datafolder = datafolder.joinpath({'original': '', 'modified': 'PagePlusOutput'}.get(datastate))
        elif Path(datafolder).exists() is not None:
            datafolder = Path(datafolder)
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
            [zip_file.write(file) for idx, file in enumerate(sorted([file for file in datafolder.glob('*.xml') if
                                                                     file.is_file() and file.name.lower not in [
                                                                         'metadata.xml', 'mets.xml']])) if
             not pages or idx + 1 in pages]
        # Check if we have data to update
        file_data.seek(0, 2)
        if file_data.tell() == 0:
            return
        # Reset the pointer to the beginning of the BytesIO object
        file_data.seek(0, 0)

        # Update transcription in eS
        with Status("Uploading documents") as status:
            escr.upload_part_transcription(document_pk, transcription_name, transcription_name + '.zip', file_data,
                                       override=overwrite)


    @app.command()
    def copy_document(
            datafolder: Annotated[
                str, typer.Option('--datafolder', '-f', help="Environmental name pointing to an existing path")],
            datastate: Annotated[Optional[DataState], typer.Option('--datastate', '-s',
                                                                   help="Choose the documents inside this folder with "
                                                                        "'original', or the 'modified' scripts inside "
                                                                        "the subfolder (PagePlusOutput).",
                                                                   case_sensitive=False)],
            outputdir: Annotated[Path, typer.Option('--outputdir', '-o',
                                                    help="Path to the output directory where the text files will be saved")]) -> None:
        """
        Copy pages of from an enviromental path to another location
        Returns:
        None
        """
        datafolder = Path(get_key(find_dotenv(), ES_PREFIX + datafolder.upper())).joinpath(
            {'original': '', 'modified': 'PagePlusOutput'}.get(datastate))
        if datafolder.exists():
            Path(outputdir).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(datafolder, outputdir)


    @app.command()
    def open_datafolder(datafolder: Annotated[
        str, typer.Option('--datafolder', '-f', help="Environmental name pointing to an existing path")],
                        ) -> None:
        """
        Open a folder in the file explorer, works for Windows, macOS, and Linux.
        """
        datafolder = Path(get_key(find_dotenv(), ES_PREFIX + datafolder.upper()))
        if datafolder == '' or datafolder is None or not Path(datafolder).exists():
            print(f"{datafolder} can't be opened!")
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
