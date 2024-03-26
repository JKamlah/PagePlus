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
    from dotenv import load_dotenv, find_dotenv, get_key, set_key, dotenv_values, unset_key

    from pageplus.utils.constants import Environments, WorkState, Bool2OnOff
    from pageplus.utils.envs import str_to_env, filter_envs
    from pageplus.utils.workspace import Workspace
    from pageplus.utils.api import API

    es_workspace = Workspace(Environments.ESCRIPTORIUM)
    es_api = API(Environments.ESCRIPTORIUM)

    ### PACKAGE ###
    @app.command(rich_help_panel="Package")
    def update_package() -> None:
        """
        Updates PagePlus-transkribus-utils based on acdh-transkribus-utils
        by Peter Andorfer, Matthias Schlögl, Carl Friedrich Haak!
        """
        """
        Updates escriptorium-connector by Bronson Brown-deVost!
        """
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-I", "escriptorium-connector"])

    ### CONSTANTS ###
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

    ### SETTINGS ###
    @app.command(rich_help_panel="Settings")
    def set_base_url(base_url: Annotated[str, typer.Argument(help="URL to Transkribus")]) -> None:
        """
        Write the URL of the Transkribus instance if it not refers to the official url
        https://transkribus.eu/TrpServer/rest to the .env file
        Returns:
        None
        """
        es_api.base_url = base_url

    @app.command(rich_help_panel="Settings")
    def set_credentials(name: Annotated[str, typer.Argument(help="Username for Transkribus")],
                        password: Annotated[str, typer.Argument(help="Password for Transkribus")]) -> None:
        """
        Write your credentials to the .env file
        Returns:
        None
        """
        es_api.credentials = (name, password)

    @app.command(rich_help_panel="Settings")
    def show_settings() -> None:
        """
        Print your current settings from the .env file
        Returns:
        None
        """
        es_api.show_settings()


    ### WORKSPACE ###
    def validate_workspace(ctx: typer.Context, param: typer.CallbackParam, value: str) -> str:
        """
        Callback function to validate the workspace option against the dynamic list,
        ensuring case-insensitive comparison.
        """
        return es_workspace.validate(value)

    @app.command(rich_help_panel="Workspace")
    def show_workspaces() -> None:
        """
        Print all workspaces
        Returns:
        None
        """
        es_workspace.show()

    @app.command(rich_help_panel="Workspace")
    def load_workspace(workspace: Annotated[str, typer.Argument(help="Set environmental name",
                                                                  callback=validate_workspace)]) -> None:
        """
        Set default workspace
        Returns:
        None
        """
        es_workspace.load(workspace)

    @app.command(rich_help_panel="Workspace")
    def update_workspaces() -> None:
        """
        Check if the workspaces still exist and updates the dotenv
        Returns:
        None
        """
        es_workspace.update()

    @app.command(rich_help_panel="Workspace")
    def delete_workspace(workspace: Annotated[str, typer.Argument(help="Set environmental name",
                                                                  callback=validate_workspace)]) -> None:
        """
        Deletes an existing workspace
        Returns:
        None
        """
        es_workspace.delete(workspace)

    @app.command(rich_help_panel="Workspace")
    def copy_workspace(destination_path: Annotated[Path,
                       typer.Argument(help="Path to the output directory where the text files will be saved")],
                        workspace: Annotated[str,
                       typer.Argument(help=f"Workspace name pointing to an existing path",
                                      callback=validate_workspace)] = None,
                       new_workspace: Annotated[str,
                       typer.Option(help=f"If set a new workspace is created.")] = "") \
            -> None:
        """
        Copy pages of from a workspace path to another location
        Returns:
        None
        """
        es_workspace.copy(destination_path, workspace, new_workspace)

    @app.command(rich_help_panel="Workspace")
    def open_workspace(workspace: Annotated[
        str, typer.Argument(help=f"Workspace name pointing to an existing path",
                            callback=validate_workspace)] = None) -> None:
        """
        Open a workspace folder in the file explorer, works for Windows, macOS, and Linux.
        """
        es_workspace.open(workspace)

    ### DOCUMENTS ###
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
        escr = EscriptoriumConnector(es_api.base_url, *es_api.credentials, es_api.api_key, es_api.api_base)
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

    @app.command(rich_help_panel="Document")
    def load_local_document(
            inputdir: Annotated[
                Path, typer.Argument(help="Path to the output directory where the text files will be saved")],
            workspace: Annotated[str, typer.Argument(help="Set environmental name")],
            overwrite_workspace: Annotated[bool, typer.Option(help="Overwrite environmental name")] = False,
            loading: Annotated[bool, typer.Option(help="Load the created workspace as default")] = True):
        """
        Set an environmental variable to an existing folder
        Returns:
        None
        """
        #TODO: Validationcheck missing
        load_dotenv()
        if workspace in es_workspace.names() and not overwrite_workspace:
            print(f"[red bold]Warning:[/red bold] The environment variable {workspace} already exists."
                  " Please set [green]overwrite-workspace[/green] "
                  "to True, if you want to overwrite the workspace.")
        if inputdir.is_dir():
            set_key(find_dotenv(), es_workspace.prefix_ws + workspace, str(inputdir.absolute()))
            if loading:
                load_workspace(es_workspace.prefix_ws + workspace)
        else:
            print(f"[red]Warning:[/red] The inputdir does not point to an existing folder.")


    @app.command(rich_help_panel="Document")
    def load_document(document_pk: Annotated[int, typer.Argument(help="Document's primary key (pk).")],
                      transcription_pk: Annotated[int,
                      typer.Argument(help="Transcription's primary key (pk).")],
                      pages: Annotated[Optional[List[int]],
                             typer.Option("--pages", "-p",
                                   help="Page selection. If not set all pages get loaded.")] = None,
                      load_images: Annotated[bool, typer.Option(help="Store also the corresponding images")] = False,
                      folderpath: Annotated[Optional[Path], typer.Option("--folderpath", "-f",
                                                                         help="Path to store the loaded document. If "
                                                                              "not set it get stored in the workspace "
                                                                              "directory.")] = None,
                      workspace: Annotated[Optional[str], typer.Option("--workspace", "-w",
                                                                       help="Name of environmental variable, which "
                                                                            "stores the path to loaded document. The "
                                                                            "name get's appended to 'ESCRIPTORIUM_WS_' and "
                                                                            "automatically cast to uppercase. E.g. "
                                                                            "new data -> ESCRIPTORIUM_WS_NEW_DATA.")] = "MAIN",
                      overwrite_ws: Annotated[bool, typer.Option(help="If workspace already exists the old data gets removed.")] = False,
                      loading: Annotated[bool, typer.Option(help="Load the created workspace as default")] = True) -> None:
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
        if workspace == '':
            print("Please provide a valid workspace or load workspace.")
            return
        if not es_api.valid_login():
            return
        escr = EscriptoriumConnector(es_api.base_url, *es_api.credentials, es_api.api_key, es_api.api_base_url)

        parts = escr.get_document_parts(document_pk).results
        parts_json = escr.http.get(f"{escr.api_url}documents/{document_pk}/parts/").json()['results']
        parts_pk = [part.pk for part in parts]

        with Status("Downloading transcription") as status:
            zipped_pagexmls_binary = escr.download_part_pagexml_transcription(document_pk, parts_pk, transcription_pk)

        zipped_pagexmls = zipfile.ZipFile(BytesIO(zipped_pagexmls_binary))

        wsfolder = Path(tempfile.mkdtemp(prefix=es_workspace.prefix_dir(), dir=es_workspace.dir())) \
                   if folderpath is None else Path(folderpath)
        wsfolder.mkdir(parents=True, exist_ok=True)

        if load_images:
            with Status("Downloading images") as status:
                for part in parts:
                    print(f"{escr.base_url}{part.image.uri}".replace('escriptorium/escriptorium', 'escriptorium'))
                    r = escr.http.get(f"{escr.base_url}{part.image.uri.lstrip('/')}"
                                      .replace('escriptorium/escriptorium', 'escriptorium'))
                    image = r.content
                    wsfolder.joinpath(part.filename).open('wb').write(image)

        # Load additional information
        # project_information = escr.get_projects()
        # TODO: Find project name and/or id
        metadata = {es_workspace.env: {'project': {'document':
                                           {'document_pk': document_pk,
                                            'transcription_pk': transcription_pk,
                                            'downloaded at': datetime.now().strftime('%H_%M_%d_%m_%Y'),
                                            'downloaded from': envs.get(es_workspace.prefix + 'URL', ''),
                                            'downloaded by': envs.get(es_workspace.prefix + 'USERNAME', ''),
                                            'page': parts_json}}}}

        with open(wsfolder.joinpath('metadata.pageplus.json'), 'w') as meta:
            json.dump(metadata, meta, indent=4)

        zipped_pagexmls.extractall(wsfolder)

        ws_absolute = es_workspace.prefix_ws + workspace
        current_folder = envs.get(ws_absolute, '')
        if current_folder is not None and current_folder != '' and Path(current_folder).exists():
            if overwrite_ws:
                rmtree(current_folder)
            else:
                print(f"The data in folder {Path(current_folder).absolute()} is now unset. "
                      f"You can load it with the load local documents function.")
        set_key(find_dotenv(), ws_absolute, str(wsfolder.absolute()))
        if loading:
            load_workspace(workspace)
        print(f"The data was successfully stored in: [bold purple]{str(wsfolder.absolute())}[/bold purple]")
        print(f"And be access via the eScriptorium workspace: [bold green]{workspace}[/bold green]")


    @app.command(rich_help_panel="Document")
    def update_document(
            workspace: Annotated[str, typer.Option(help="A path or an environmental name pointing to an existing path",
                                                                  callback=validate_workspace)] = None,
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

        if not es_api.valid_login():
            return

        escr = EscriptoriumConnector(es_api.base_url, *es_api.credentials, es_api.api_key, es_api.api_base)
        overwrite = Bool2OnOff.get(overwrite)

        # Create a BytesIO object to hold the zip file in memory
        file_data = BytesIO()
        if es_workspace.prefix_ws + workspace in filter_envs(es_workspace.prefix).keys():
            wsfolder = Path(envs[es_workspace.prefix_ws + workspace])
            metadata = json.loads(wsfolder.joinpath('metadata.pageplus.json').open('r').read())
            metadata = metadata.get(es_workspace.env, '').get('project', '').get('document', '')
            document_pk = metadata.get('document_pk', None) if document_pk is None else document_pk
            transcription_pk = metadata.get('transcription_pk', None) if transcription_pk is None else transcription_pk
            wsfolder = wsfolder.joinpath(envs.get(Environments.PAGEPLUS.as_prefix_workstate(workstate), ''))
        else:
            return
        if transcription_name is None and transcription_pk is not None:
            transcription_name = escr.get_document_transcription(document_pk, transcription_pk).name
        if transcription_name is None:
            return
        if not wsfolder.exists() or document_pk is None or transcription_name is None:
            return

        parts = [wsfolder.joinpath(part.filename).with_suffix('.xml') for idx, part in
                 enumerate(escr.get_document_parts(document_pk).results) if not pages or (idx + 1 in pages)]
        print(parts)
        # Create a ZipFile object with the BytesIO object as file, in write mode
        with zipfile.ZipFile(file_data, 'w', zipfile.ZIP_DEFLATED) as zip_file:
            # Recursively add files to the zip file
            [zip_file.write(file) for file in parts if file.exists()]
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


if __name__ == "__main__":
    app()
