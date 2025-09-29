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
import io
from io import BytesIO
from pathlib import Path
from shutil import rmtree
from typing import List, Optional

import pandas as pd
import typer
from rich import print
from rich.status import Status
from rich.table import Table
from typing_extensions import Annotated

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
    from escriptorium_connector.dtos import (
        PostPart,
        PostProject,
        PostDocument,
        ReadDirection,
        LineOffset
    )
    from dotenv import load_dotenv, set_key, dotenv_values

    from pageplus.utils.constants import Environments, Bool2OnOff
    from pageplus.utils.envs import str_to_env, get_env_path
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
        load_dotenv(get_env_path())
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
        load_dotenv(get_env_path())
        envs = dotenv_values(get_env_path())
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
            set_key(get_env_path(), ws_absolute, str(wsfolder.absolute()))
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
        load_dotenv(get_env_path())

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

    @app.command(rich_help_panel="Document")
    def create_project_document(
            project_name: Annotated[str, typer.Argument(help="Name of the project to create or existing procject pk")],
            document_name: Annotated[str, typer.Argument(help="Name of the document to create")],
            main_script: Annotated[Optional[str], typer.Option("--main-script", "-s",
                                                               help="Main script of the document")] = "Latin",
            images: Annotated[List[Path], typer.Option("--images", "-i",
                                                       help="Paths to image files to upload")] = None,
            xml_files: Annotated[List[Path], typer.Option("--xml", "-x",
                                                          help="Paths to XML files to upload")] = None,
            transcription_name: Annotated[Optional[str], typer.Option("--transcription-name", "-n",
                                                                      help="Name for the transcription")] = None,
            workspace: Annotated[Optional[str], typer.Option("--workspace", "-w",
                                                             help="Workspace name to store the created project info")] = None) -> None:
        """
        Creates a new project and document in eScriptorium and uploads images and XML files.

        This function will:
        1. Create a new project with the given name (or use existing project PK)
        2. Create a new document within that project
        3. Upload image files to the document using create_document_part
        4. Upload XML transcription files to the document

        Args:
            project_name: Name of the project to create OR existing project PK (integer)
            document_name: Name of the document to create

        Returns:
        None
        """
        load_dotenv(get_env_path())
        envs = dotenv_values(get_env_path())

        if not es_api.valid_login():
            return

        escr = EscriptoriumConnector(
            es_api.base_url,
            *es_api.credentials,
            es_api.api_key,
            es_api.api_base_url,
            instance_name=es_api.instance_name)

        try:
            # Step 1: Create project or use existing project PK
            try:
                # Try to parse as integer (existing project PK)
                project_pk = int(project_name)
                with Status(f"Using existing project PK: {project_pk}"):
                    # Verify project exists by trying to get it
                    project_data = escr.get_project(project_pk)
                    print(f"[green]✓[/green] Using existing project: {project_data.name} (PK: {project_pk})")
            except ValueError:
                # Not an integer, treat as project name and create new project
                with Status(f"Creating project '{project_name}'"):
                    project_post_data = PostProject(name=project_name)
                    project_data = escr.create_project(project_post_data)
                    project_pk = project_data.id
                    print(f"[green]✓[/green] Project created: {project_name} (PK: {project_pk})")

            # Step 2: Create document
            with Status(f"Creating document '{document_name}'"):
                doc_post_data = PostDocument(
                    name=document_name,
                    project=project_data.slug,
                    main_script=main_script,
                    read_direction=ReadDirection.LTR,
                    line_offset=LineOffset.BASELINE
                )
                document_data = escr.create_document(doc_post_data)
                document_pk = document_data.pk
                print(f"[green]✓[/green] Document created: {document_name} (PK: {document_pk})")

            # Step 3: Upload images if provided
            if images:
                with Status(f"Uploading {len(images)} image(s)"):
                    for i, image_path in enumerate(images, 1):
                        if not image_path.exists():
                            print(f"[yellow]⚠[/yellow] Image file not found: {image_path}")
                            continue

                        try:
                            # Read image data
                            with open(image_path, 'rb') as f:
                                image_data = f.read()

                            # Create PostPart object
                            part_info = PostPart(
                                name=image_path.stem,
                                typology=None,  # Can be set to specific typology if needed
                                source="upload"
                            )

                            # Upload the image
                            part_data = escr.create_document_part(
                                document_pk,
                                part_info,
                                image_path.name,
                                image_data
                            )
                            print(f"[green]✓[/green] Image {i}/{len(images)} uploaded: {image_path.name} (PK: {part_data.pk})")
                        except Exception as e:
                            print(f"[red]✗[/red] Failed to upload image {image_path.name}: {e}")

            # Step 4: Upload XML files if provided
            if xml_files:
                with Status(f"Uploading {len(xml_files)} XML file(s)"):
                    # Create a BytesIO object to hold the zip file in memory
                    file_data = BytesIO()

                    with zipfile.ZipFile(file_data, 'w', zipfile.ZIP_DEFLATED) as zip_file:
                        for xml_file in xml_files:
                            if xml_file.exists():
                                zip_file.write(xml_file, xml_file.name)
                            else:
                                print(f"[yellow]⚠[/yellow] XML file not found: {xml_file}")

                    # Check if we have data to upload
                    file_data.seek(0, 2)
                    if file_data.tell() > 0:
                        file_data.seek(0, 0)

                        # Use document name as transcription name if not provided
                        trans_name = transcription_name if transcription_name else f"{document_name}_transcription"

                        try:
                            escr.upload_part_transcription(
                                document_pk,
                                trans_name,
                                f"{trans_name}.zip",
                                file_data,
                                override=True
                            )
                            print(f"[green]✓[/green] XML files uploaded as transcription: {trans_name}")
                        except Exception as e:
                            print(f"[red]✗[/red] Failed to upload XML files: {e}")
                    else:
                        print("[yellow]⚠[/yellow] No valid XML files found to upload")

            # Step 5: Save project info to workspace if requested
            if workspace:
                workspace = str_to_env(workspace)
                ws_absolute = es_workspace.prefix_ws + workspace

                # Create metadata
                metadata = {
                    es_workspace.env: {
                        'project': {
                            'name': project_name,
                            'pk': project_pk,
                            'document': {
                                'name': document_name,
                                'pk': document_pk,
                                'transcription_name': transcription_name or f"{document_name}_transcription",
                                'created_at': datetime.now().strftime('%H_%M_%d_%m_%Y'),
                                'created_by': envs.get(es_workspace.prefix + 'USERNAME', ''),
                                'images_uploaded': len(images) if images else 0,
                                'xml_files_uploaded': len(xml_files) if xml_files else 0
                            }
                        }
                    }
                }

                # Save metadata to a temporary file
                temp_dir = Path(tempfile.mkdtemp(prefix=es_workspace.prefix_dir(), dir=es_workspace.dir()))
                with open(temp_dir / 'metadata.pageplus.json', 'w') as meta:
                    json.dump(metadata, meta, indent=4)

                # Set workspace environment variable
                set_key(get_env_path(), ws_absolute, str(temp_dir.absolute()))
                print(f"[green]✓[/green] Project info saved to workspace: {workspace}")

            print("\n[bold green]Successfully created project and document![/bold green]")
            print(f"Project: {project_name} (PK: {project_pk})")
            print(f"Document: {document_name} (PK: {document_pk})")
            if images:
                print(f"Images uploaded: {len(images)}")
            if xml_files:
                print(f"XML files uploaded: {len(xml_files)}")

        except Exception as e:
            print(f"[red]Error creating project/document: {e}[/red]")
            raise

    @app.command(rich_help_panel="Document")
    def add_parts(
            project_name: Annotated[str, typer.Argument(help="Project primary name")],
            document_pk: Annotated[int, typer.Argument(help="Document primary key (pk)")],
            images: Annotated[List[Path], typer.Option("--images", "-i",
                                                       help="Paths to image files to upload")] = None,
            xml_files: Annotated[List[Path], typer.Option("--xml", "-x",
                                                          help="Paths to XML files to upload")] = None,
            transcription_name: Annotated[Optional[str], typer.Option("--transcription-name", "-n",
                                                                      help="Name for the transcription")] = None) -> None:
        """
        Add parts (images/transcriptions) to an existing eScriptorium document.

        This function will:
        1. Upload image files to the document using create_document_part
        2. Upload XML transcription files to the document

        Args:
            project_pk: Primary key of the existing project
            document_pk: Primary key of the existing document
            images: List of image file paths to upload
            xml_files: List of XML file paths to upload
            transcription_name: Name for the transcription (optional)

        Returns:
        None
        """
        load_dotenv(get_env_path())

        if not es_api.valid_login():
            return

        escr = EscriptoriumConnector(
            es_api.base_url,
            *es_api.credentials,
            es_api.api_key,
            es_api.api_base_url,
            instance_name=es_api.instance_name)

        try:
            # Verify project and document exist
            with Status("Verifying project and document"):
                try:
                    print(f"[dim]Searching for project: '{project_name}'[/dim]")
                    project_pk = escr.get_project_pk_by_name(project_name)
                    if project_pk is None:
                        print(f"[red]Error:[/red] Project '{project_name}' not found.")
                        print("[yellow]Please check the project name or use the project PK directly.[/yellow]")
                        # List available projects for debugging
                        try:
                            all_projects = escr.get_projects()
                            print(f"[dim]Available projects (first 10): {[p.name for p in all_projects.results[:10]]}[/dim]")
                            # Also check for case-insensitive matches
                            case_insensitive_matches = [p.name for p in all_projects.results if p.name.lower() == project_name.lower()]
                            if case_insensitive_matches:
                                print(f"[dim]Case-insensitive matches found: {case_insensitive_matches}[/dim]")
                        except Exception:
                            pass
                        return
                    project_data = escr.get_project(project_pk)
                    print(f"[green]✓[/green] Project: {project_data.name} (PK: {project_pk})")
                except Exception as e:
                    error_type = type(e).__name__
                    if "EscriptoriumConnectorDtoValidationError" in error_type or "ValidationError" in str(e):
                        print("[red]Error:[/red] eScriptorium connector library version incompatibility detected.")
                        print("[yellow]Please try using the project PK directly instead of project name.[/yellow]")
                        print("[yellow]You can find the project PK in the eScriptorium web interface.[/yellow]")
                        print(f"[dim]Error details: {error_type}[/dim]")
                        return
                    else:
                        raise e

                document_data = escr.get_document(document_pk)
                print(f"[green]✓[/green] Document: {document_data.name} (PK: {document_pk})")

            # Upload images if provided
            if images:
                with Status(f"Uploading {len(images)} image(s)"):
                    for i, image_path in enumerate(images, 1):
                        if not image_path.exists():
                            print(f"[yellow]⚠[/yellow] Image file not found: {image_path}")
                            continue

                        try:
                            # Read image data
                            with open(image_path, 'rb') as f:
                                image_data = f.read()

                            # Create PostPart object
                            part_info = PostPart(
                                name=image_path.stem,
                                typology=None,  # Can be set to specific typology if needed
                                source="upload"
                            )

                            # Upload the image
                            part_data = escr.create_document_part(
                                document_pk,
                                part_info,
                                image_path.name,
                                image_data
                            )
                            print(f"[green]✓[/green] Image {i}/{len(images)} uploaded: {image_path.name} (PK: {part_data.pk})")
                        except Exception as e:
                            print(f"[red]✗[/red] Failed to upload image {image_path.name}: {e}")

            # Upload XML files if provided
            if xml_files:
                with Status(f"Uploading {len(xml_files)} XML file(s)"):
                    # Create a BytesIO object to hold the zip file in memory
                    file_data = BytesIO()

                    with zipfile.ZipFile(file_data, 'w', zipfile.ZIP_DEFLATED) as zip_file:
                        for xml_file in xml_files:
                            if xml_file.exists():
                                zip_file.write(xml_file, xml_file.name)
                            else:
                                print(f"[yellow]⚠[/yellow] XML file not found: {xml_file}")

                    # Check if we have data to upload
                    file_data.seek(0, 2)
                    if file_data.tell() > 0:
                        file_data.seek(0, 0)

                        # Use document name as transcription name if not provided
                        trans_name = transcription_name if transcription_name else f"{document_data.name}_transcription"

                        try:
                            escr.upload_part_transcription(
                                document_pk,
                                trans_name,
                                f"{trans_name}.zip",
                                file_data,
                                override=True
                            )
                            print(f"[green]✓[/green] XML files uploaded as transcription: {trans_name}")
                        except Exception as e:
                            print(f"[red]✗[/red] Failed to upload XML files: {e}")
                    else:
                        print("[yellow]⚠[/yellow] No valid XML files found to upload")

            print("\n[bold green]Successfully added parts to document![/bold green]")
            print(f"Project: {project_data.name} (PK: {project_pk})")
            print(f"Document: {document_data.name} (PK: {document_pk})")
            if images:
                print(f"Images uploaded: {len(images)}")
            if xml_files:
                print(f"XML files uploaded: {len(xml_files)}")

        except Exception as e:
            print(f"[red]Error adding parts to document: {e}[/red]")
            raise


@app.command(rich_help_panel="Document")
def add_parts_by_pk(
        project_pk: Annotated[int, typer.Argument(help="Project primary key (pk)")],
        document_pk: Annotated[int, typer.Argument(help="Document primary key (pk)")],
        images: Annotated[List[Path], typer.Option("--images", "-i",
                                                   help="Paths to image files to upload")] = None,
        xml_files: Annotated[List[Path], typer.Option("--xml", "-x",
                                                      help="Paths to XML files to upload")] = None,
        transcription_name: Annotated[Optional[str], typer.Option("--transcription-name", "-n",
                                                                  help="Name for the transcription")] = None) -> None:
    """
    Add parts (images/transcriptions) to an existing eScriptorium document using project PK.

    This function will:
    1. Upload image files to the document using create_document_part
    2. Upload XML transcription files to the document

    Args:
        project_pk: Primary key of the existing project
        document_pk: Primary key of the existing document
        images: List of image file paths to upload
        xml_files: List of XML file paths to upload
        transcription_name: Name for the transcription (optional)
    """
    es_api = EscriptoriumAPI()
    if not es_api.valid_login():
        return

    escr = EscriptoriumConnector(
        es_api.base_url,
        *es_api.credentials,
        es_api.api_key,
        es_api.api_base_url,
        instance_name=es_api.instance_name)

    try:
        # Verify project and document exist
        with Status("Verifying project and document"):
            project_data = escr.get_project(project_pk)
            document_data = escr.get_document(document_pk)
            print(f"[green]✓[/green] Project: {project_data.name} (PK: {project_pk})")
            print(f"[green]✓[/green] Document: {document_data.name} (PK: {document_pk})")

        # Upload images if provided
        if images:
            with Status(f"Uploading {len(images)} image(s)"):
                for i, image_path in enumerate(images, 1):
                    if not image_path.exists():
                        print(f"[red]Warning:[/red] Image file not found: {image_path}")
                        continue

                    try:
                        # Read image data
                        with open(image_path, 'rb') as f:
                            image_data = f.read()

                        # Create PostPart object
                        part_info = PostPart(
                            name=image_path.stem,
                            typology=None,  # Can be set to specific typology if needed
                            source="upload"
                        )

                        # Upload the image
                        escr.create_document_part(
                            document_pk,
                            part_info,
                            image_path.name,
                            image_data
                        )

                        print(f"[green]✓[/green] Uploaded image {i}/{len(images)}: {image_path.name}")

                    except Exception as e:
                        print(f"[red]Error uploading {image_path.name}:[/red] {e}")

        # Upload XML files if provided
        if xml_files:
            with Status(f"Uploading {len(xml_files)} XML file(s)"):
                # Create a ZIP file in memory
                zip_buffer = io.BytesIO()
                with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
                    for xml_path in xml_files:
                        if not xml_path.exists():
                            print(f"[red]Warning:[/red] XML file not found: {xml_path}")
                            continue
                        zip_file.write(xml_path, xml_path.name)

                zip_buffer.seek(0)

                # Upload the ZIP file as transcription
                transcription_name_final = transcription_name or f"Transcription_{document_pk}"
                try:
                    escr.create_document_transcription(
                        document_pk,
                        transcription_name_final,
                        zip_buffer.getvalue(),
                        f"{transcription_name_final}.zip"
                    )
                    print(f"[green]✓[/green] Uploaded transcription: {transcription_name_final}")
                except Exception as e:
                    print(f"[red]Error uploading transcription:[/red] {e}")

        print(f"[green]✓[/green] Parts added successfully to document {document_data.name}")

    except Exception as e:
        print(f"[red]Error:[/red] {e}")
        return


if __name__ == "__main__":
    app()
