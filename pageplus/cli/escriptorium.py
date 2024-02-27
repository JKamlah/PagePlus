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
from typing import List

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
    import logging

    from escriptorium_connector import EscriptoriumConnector
    from dotenv import load_dotenv, find_dotenv, get_key, set_key, dotenv_values

    from pageplus.utils.constants import DotEnvPrefixes, WorkState, Bool2OnOff, WORKSPACE_PREFIX
    from pageplus.utils.fs import str_to_env

    logging.getLogger("requests").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)

    SERVICE = DotEnvPrefixes.ESCRIPTORIUM.lower()
    PREFIX = DotEnvPrefixes.ESCRIPTORIUM + '_'
    PREFIX_WS = DotEnvPrefixes.ESCRIPTORIUM + '_' + WORKSPACE_PREFIX


    class DataFilter(str, Enum):
        """
        Filter options of the data for escriptorium
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


    @app.command()
    def set_url(url: Annotated[str, typer.Argument(help="URL to eScriptorium")]) -> None:
        """
        Write the URL of the eScritpriums instance (e.g. https://www.escriptorium.fr) to the .env file
        Returns:
        None
        """
        try:
            dotfile = find_dotenv()
            set_key(dotfile, PREFIX + "URL", url)
            print("[green]The url updated successfully.[green]")
        except Exception as e:
            print(f"[red]Failed to update the url: {e}[red]")


    @app.command()
    def set_credentials(name: Annotated[str, typer.Argument(help="Username for eScriptorium")],
                        password: Annotated[str, typer.Argument(help="Password for eScriptorium")]) -> None:
        """
        Write your credentials to the .env file
        Returns:
        None
        """
        try:
            dotfile = find_dotenv()
            set_key(dotfile, f"{PREFIX}USERNAME", name)
            set_key(dotfile, f"{PREFIX}PASSWORD", password)
            print("[green]Credentials updated successfully.[green]")
        except Exception as e:
            print(f"[red]Failed to update credentials: {e}[red]")


    @app.command()
    def set_api_url(url: Annotated[str, typer.Argument(help="API url for eScriptorium")]) -> None:
        """
        Set if api url differs from base-url/api and api-key should be used
        WARNING: Currently
        Returns:
        None
        """
        dotfile = find_dotenv()
        set_key(dotfile, PREFIX + "API_URL", url)


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
            set_key(dotfile, PREFIX + "API_KEY", key)


    @app.command()
    def valid_login() -> bool:
        envs = dotenv_values()
        check = all(
            [envs.get(PREFIX + 'URL', None), envs.get(PREFIX + 'USERNAME', None), envs.get(PREFIX + 'PASSWORD', None)])
        check_api = all([envs.get(PREFIX + 'API_KEY', None),
                         any([envs.get(PREFIX + 'URL', None), envs.get(PREFIX + 'API_URL', None)])])
        if not check and not check_api:
            print(
                f"[red bold]Missing login information:[/red bold] [red]Ensure that the URL, username, and password or "
                f"API URL and key are correctly configured.[/red]")
            return False
        return True


    def get_envgroup(group: DotEnvPrefixes) -> dict:
        """
        Filters dotenv values for a specific Prefix
        Returns:
            dict
        """
        load_dotenv()
        envs = dotenv_values()
        return dict([(var, key) for (var, key) in envs.items() if group.value.upper() in var.upper()])


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
        [table.add_row(var, key) if var != PREFIX+"PASSWORD" else table.add_row(var, key[:3] + '***') for
         (var, key) in dotenv_values().items() if var.startswith(PREFIX)]
        print(table)

    @app.command()
    def show_workspaces() -> None:
        """
        Print all workspaces
        Returns:
        None
        """
        table = Table(title="eScriptorium's workspaces")
        table.add_column("eScriptorium workspace", justify="right", style="cyan", no_wrap=True)
        table.add_column("Workspace folder")
        [table.add_row(var.replace(PREFIX_WS, ''), key) for (var, key) in dotenv_values().items()
         if var.startswith(PREFIX_WS)]
        print(table)


    @app.command()
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
        envs = dotenv_values()
        if not valid_login():
            return
        escr = EscriptoriumConnector(envs.get(PREFIX + 'URL', None),
                                     envs.get(PREFIX + 'USERNAME', None),
                                     envs.get(PREFIX + 'PASSWORD', None),
                                     envs.get(PREFIX + 'API_KEY', None),
                                     envs.get(PREFIX + 'API_URL', None))
        if len(filter_by) != len(search_term):
            print("Please provide for each filter a search term")
            return

        with Status("Searching for documents") as status:
            try:
                documents = escr.get_documents()
            except:
                print(f"[red]Missing login information: Ensure that the URL, username, and password or "
                      f"API URL and key are correctly configured.[/red]")
                return

        print(f"[bold green]eScriptorium Document Search Report[/bold green] - [white]Version 1.0[/white]")
        print(f"Total documents found: {documents.count}")
        count = documents.count
        flag = 0 if case_sensitive else re.IGNORECASE
        if filter_by is not None:
            for idx, document in enumerate(documents.results[::-1]):
                for f, s in zip(filter_by, search_term):
                    if not ((f == "Project" and re.match(s, document.project, flags=flag)) or
                            (f == "Document" and re.match(s, document.name, flags=flag)) or
                            (f == "Transcription" and any(
                                [re.match(s, trans.name, flags=flag) for trans in document.transcriptions]))):
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


    @app.command()
    def load_document(document_pk: Annotated[int, typer.Argument(help="Document's primary key (pk).")],
                      transcription_pk: Annotated[int,
                      typer.Argument(help="Transcription's primary key (pk).")],
                      pages: Annotated[Optional[List[int]],
                      typer.Option("--pages", "-p",
                                   help="Page selection. If not set all pages get loaded.")] = None,
                      folderpath: Annotated[Optional[Path], typer.Option("--folderpath", "-f",
                                                                         help="Path to store the loaded document. If "
                                                                              "not set it get stored in a temporary "
                                                                              "folder.")] = None,
                      workspace: Annotated[Optional[str], typer.Option("--workspace", "-w",
                                                                       help="Name of enviormental variable, which "
                                                                            "stores the path to loaded document. The "
                                                                            "name get's appended to 'ESCRIPTORIUM_' and "
                                                                            "automatically cast to uppercase. E.g. "
                                                                            "new_data -> ESCRIPTORIUM_NEW_DATA.")] =
                      "MAIN") -> None:
        """
        Loads pages of a document with a specific transcription to work with PagePlus.
        For more information abouth the pk values and page numbers see the --find-documents function.
        Returns:
        None
        """
        # Create a Path object for the directory
        load_dotenv()
        envs = dotenv_values()
        workspace = str_to_env(workspace)
        if not valid_login():
            return
        escr = EscriptoriumConnector(envs.get(PREFIX + 'URL', None),
                                     envs.get(PREFIX + 'USERNAME', None),
                                     envs.get(PREFIX + 'PASSWORD', None),
                                     envs.get(PREFIX + 'API_KEY', None),
                                     envs.get(PREFIX + 'API_URL', None))

        parts_pk = [part.pk for idx, part in enumerate(escr.get_document_parts(document_pk).results) if
                    not pages or (idx + 1 in pages)]

        with Status("Downloading document") as status:
            zipped_pagexmls_binary = escr.download_part_pagexml_transcription(document_pk, parts_pk, transcription_pk)

        zipped_pagexmls = zipfile.ZipFile(BytesIO(zipped_pagexmls_binary))

        wsfolder = Path(tempfile.mkdtemp(prefix="PagePlus_")) if folderpath is None else Path(folderpath)
        wsfolder.mkdir(parents=True, exist_ok=True)

        with open(wsfolder.joinpath('metadata.pageplus.json'), 'w') as meta:
            json.dump({SERVICE: {'document_pk': document_pk,
                                   'parts_pk': parts_pk,
                                   'transcription_pk': transcription_pk,
                                   'downloaded at': datetime.now().strftime('%H_%M_%d_%m_%Y'),
                                   'downloaded from': envs.get(PREFIX + 'URL', ''),
                                   'downloaded by': envs.get(PREFIX + 'USERNAME', '')}},
                      meta, indent=4)

        zipped_pagexmls.extractall(wsfolder)

        ws_absolute = PREFIX_WS + workspace
        current_folder = envs.get(ws_absolute, '')
        if current_folder != '' and Path(current_folder).exists():
            rmtree(current_folder)
        set_key(find_dotenv(), ws_absolute, str(wsfolder.absolute()))
        print(f"The data was successfully stored in: [bold purple]{str(wsfolder.absolute())}[/bold purple]")
        print(f"And be access via the eScriptorium workspace: [bold green]{workspace}[/bold green]")


    @app.command()
    def update_document(
            workspace: Annotated[
                str, typer.Option('--workspace', '-w',
                                  help="A path or an environmental name pointing to an existing path")] = "MAIN",
            workstate: Annotated[Optional[WorkState], typer.Option('--workstate', '-s',
                                                                   help="Choose the documents inside this folder with "
                                                                        "'original', or the 'modified' scripts inside "
                                                                        "the subfolder (PagePlusOutput).",
                                                                   case_sensitive=False)] = "original",
            document_pk: Annotated[int, typer.Option("--document-pk", "-d",
                                                     help="Document's primary key (pk). (Not necessary if "
                                                          "environmental is used, but can also overwrite)")] = None,
            transcription_pk: Annotated[int, typer.Option("--transcription-pk", "-t",
                                                          help="Transcription's primary key (pk)")] = None,
            pages: Annotated[Optional[List[int]], typer.Option("--pages", "-p",
                                                               help=f"Page selection. "
                                                                    f"If not set all pages get uploaded.")] = None,
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
        workspace= str_to_env(workspace)
        escr = EscriptoriumConnector(envs[PREFIX + 'URL'],
                                     envs[PREFIX + 'USERNAME'],
                                     envs[PREFIX + 'PASSWORD'])
        overwrite = Bool2OnOff.get(overwrite)

        # Create a BytesIO object to hold the zip file in memory
        file_data = BytesIO()
        if PREFIX_WS + workspace in get_envgroup(DotEnvPrefixes.ESCRIPTORIUM).keys():
            wsfolder = Path(envs[PREFIX_WS + workspace])
            metadata = json.loads(wsfolder.joinpath('metadata.pageplus.json').open('r').read())
            metadata = metadata.get(SERVICE, '')
            document_pk = metadata.get('document_pk', None) if document_pk is None else document_pk
            transcription_pk = metadata.get('transcription_pk', None) if transcription_pk is None else transcription_pk
            wsfolder = wsfolder.joinpath(envs.get(DotEnvPrefixes.PAGEPLUS + workstate, ''))
        else:
            return
        if transcription_name is None and transcription_pk is not None:
            transcription_name = escr.get_document_transcription(document_pk, transcription_pk).name
        if transcription_name is None:
            return
        if not wsfolder.exists() or document_pk is None or transcription_name is None:
            return
        # Create a ZipFile object with the BytesIO object as file, in write mode
        with zipfile.ZipFile(file_data, 'w', zipfile.ZIP_DEFLATED) as zip_file:
            # Recursively add files to the zip file
            [zip_file.write(file) for idx, file in enumerate(sorted([file for file in wsfolder.glob('*.xml') if
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
        with Status("Updating document") as status:
            escr.upload_part_transcription(document_pk, transcription_name, transcription_name + '.zip', file_data,
                                           override=overwrite)
        print("Updating completed!")

    @app.command()
    def copy_workspace(workspace: Annotated[str,
                       typer.Argument(help=f"Workspace name pointing to an existing path")],
                       destination_path: Annotated[Path,
                       typer.Argument(help="Path to the output directory where the text files will be saved")]) \
            -> None:
        """
        Copy pages of from a workspace path to another location
        Returns:
        None
        """
        load_dotenv()
        envs = dotenv_values()
        workspace = str_to_env(workspace)
        wsfolder = Path(get_key(find_dotenv(), PREFIX_WS + workspace)).joinpath(
            envs.get(DotEnvPrefixes.PAGEPLUS, ''))
        if wsfolder.exists():
            Path(destination_path).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(wsfolder, destination_path)


    @app.command()
    def open_workspace(workspace: Annotated[
        str, typer.Argument(help=f"Workspace name pointing to an existing path")] = "MAIN") -> None:
        """
        Open a workspace folder in the file explorer, works for Windows, macOS, and Linux.
        """
        workspace= str_to_env(workspace)
        wsfolder = Path(get_key(find_dotenv(), PREFIX_WS + workspace))
        if wsfolder == '' or wsfolder is None or not Path(wsfolder).exists():
            print(f"{wsfolder} can't be opened!")
            return
        if sys.platform == "win32":
            # Windows
            os.startfile(wsfolder)
        elif sys.platform == "darwin":
            # macOS
            subprocess.run(["open", wsfolder])
        else:
            # Linux and other Unix-like OS
            subprocess.run(["xdg-open", wsfolder])

if __name__ == "__main__":
    app()
