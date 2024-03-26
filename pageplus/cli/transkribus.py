import json
import re
import subprocess
import sys
import tempfile
from collections import defaultdict
from enum import Enum
from importlib import util
from pathlib import Path
from shutil import rmtree
from typing import List

import requests
import typer
from rich import print
from rich.status import Status
from rich.table import Table
from typing_extensions import Annotated, Optional

app = typer.Typer()

if (spec := util.find_spec('transkribus_utils')) is None:

    @app.command()
    def install() -> None:
        """
        Before Transkribus can be used, please use this install command
        to install PagePlus-transkribus-utils based on acdh-transkribus-utils
        by Peter Andorfer, Matthias Schlögl, Carl Friedrich Haak!
        """
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-I",
                               "git+https://github.com/JKamlah/PagePlus-transkribus-utils"])

    def validate_workspace(ctx: typer.Context, param: typer.CallbackParam, value: str) -> str:
        """
        Callback function to validate the workspace option against the dynamic list,
        ensuring case-insensitive comparison.
        """
        return Workspace().validate(value)

else:
    import logging

    from transkribus_utils.transkribus_utils import PagePlusTranskribusUtils
    from dotenv import load_dotenv, find_dotenv, get_key, set_key, dotenv_values, unset_key

    from pageplus.utils.constants import Environments, WorkState
    from pageplus.utils.envs import str_to_env, filter_envs
    from pageplus.utils.workspace import Workspace
    from pageplus.utils.api import API

    logging.getLogger("requests").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)

    ### CONSTANTS ###
    ts_workspace = Workspace(Environments.TRANSKRIBUS)
    ts_api = API(Environments.TRANSKRIBUS)

    class DataFilter(str, Enum):
        """
        Filter options of the data for transkribus
        """
        COLLECTION = "Collection"
        DOCUMENT = "Document"
        ROLE = "Role"
        PAGE = "Page"
        PAGESTATUS = "PageStatus"


    class DataLevel(str, Enum):
        """
        Level of transkribus data
        """
        COLLECTION = "Collection"
        DOCUMENT = "Document"
        PAGE = "Page"


    class PageStatus(str, Enum):
        """
        Status of transkribus transcriptions
        """
        NEW = "New"
        INPROGRESS = "InProgress"
        DONE = "Done"
        FINAL = "Final"
        GT = "GT"


    class Role(str, Enum):
        """
        Roles of transkribus user
        """
        OWNER = "Owner"
        EDITOR = "Editor"
        TRANSCRIBER = "Transcriber"
        READER = "Reader"

    ### PACKAGE ###
    @app.command(rich_help_panel="Package")
    def update_package() -> None:
        """
        Updates PagePlus-transkribus-utils based on acdh-transkribus-utils
        by Peter Andorfer, Matthias Schlögl, Carl Friedrich Haak!
        """
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-I",
                               "git+https://github.com/JKamlah/PagePlus-transkribus-utils"])

    ### SETTINGS ###
    @app.command(rich_help_panel="Settings")
    def set_url(url: Annotated[str, typer.Argument(help="URL to Transkribus")]) -> None:
        """
        Write the URL of the Transkribus instance if it not refers to the official url
        https://transkribus.eu/TrpServer/rest to the .env file
        Returns:
        None
        """
        ts_api.base_url = url

    @app.command(rich_help_panel="Settings")
    def set_credentials(name: Annotated[str, typer.Argument(help="Username for Transkribus")],
                        password: Annotated[str, typer.Argument(help="Password for Transkribus")]) -> None:
        """
        Write your credentials to the .env file
        Returns:
        None
        """
        ts_api.base_url = (name, password)

    @app.command(rich_help_panel="Settings")
    def show_settings() -> None:
        """
        Print your current settings from the .env file
        Returns:
        None
        """
        ts_api.show_settings()

    ### WORKSPACE ###
    def validate_workspace(ctx: typer.Context, param: typer.CallbackParam, value: str) -> str:
        """
        Callback function to validate the workspace option against the dynamic list,
        ensuring case-insensitive comparison.
        """
        return ts_workspace.validate(value)

    @app.command(rich_help_panel="Workspace")
    def show_workspaces() -> None:
        """
        Print all workspaces
        Returns:
        None
        """
        ts_workspace.show()

    @app.command(rich_help_panel="Workspace")
    def load_workspace(workspace: Annotated[str, typer.Argument(help="Set environmental name",
                                                                  callback=validate_workspace)]) -> None:
        """
        Set default workspace
        Returns:
        None
        """
        ts_workspace.load(workspace)

    @app.command(rich_help_panel="Workspace")
    def update_workspaces() -> None:
        """
        Check if the workspaces still exist and updates the dotenv
        Returns:
        None
        """
        ts_workspace.update()

    @app.command(rich_help_panel="Workspace")
    def delete_workspace(workspace: Annotated[str, typer.Argument(help="Set environmental name",
                                                                  callback=validate_workspace)]) -> None:
        """
        Deletes an existing workspace
        Returns:
        None
        """
        ts_workspace.delete(workspace)

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
        ts_workspace.copy(destination_path, workspace, new_workspace)

    @app.command(rich_help_panel="Workspace")
    def open_workspace(workspace: Annotated[
        str, typer.Argument(help=f"Workspace name pointing to an existing path",
                            callback=validate_workspace)] = None) -> None:
        """
        Open a workspace folder in the file explorer, works for Windows, macOS, and Linux.
        """
        ts_workspace.open(workspace)

    ### DOCUMENTS ###
    def valid_filter(filter_by: list, search_term: list) -> bool:
        valid = True
        for f, s in zip(filter_by, search_term):
            if f == 'PageStatus' and s.upper() not in PageStatus.__members__.keys():
                print(
                    'For transcription filter please choose one of the following: New, InProgress, Done, Final or GT.')
                valid = False
            if f == 'Role' and s.upper() not in Role.__members__.keys():
                print('For role filter please choose one of the following: Owner, Editor, Transcriber or Reader.')
                valid = False
            if f == 'Page' and not s.isdigit():
                print('For page filter please provide a minimum page number.')
                valid = False
        return valid


    def str_filter_not_match(filter_by: list, search_term: list, string: str, filter_option: str, flag=0) -> bool:
        if filter_option in filter_by:
            for s in [search_term[idx] for idx, f in enumerate(filter_by) if f == filter_option]:
                if not re.match(s, string, flags=flag):
                    return True
        return False

    @app.command(rich_help_panel="Document")
    def find_documents(filter_by: Annotated[List[DataFilter], typer.Option("--filter-by", "-f",
                                                                           help="Filter the document search by "
                                                                                "the name of the 'Collection', "
                                                                                "'Document', 'PageStatus',"
                                                                                "'Role, 'Page'",
                                                                           case_sensitive=False)],
                       search_term: Annotated[
                           List[str], typer.Option("--search-term", "-s",
                                                   help=f"RegEx search term for the filter option (Use . to find "
                                                        f"all documents). For 'PageStatus' filter the search-term "
                                                        f"is limited to: New, InProgress, Done, Final or GT."
                                                        f"For 'user' filter the search-term "
                                                        f"is limited to: Owner, Editor, Transcriber or Reader."
                                                        f"For 'pages' filter the search-term "
                                                        f"is limited to: Number of minimum pages.")],

                       case_sensitive: Annotated[Optional[bool], typer.Option(
                           help="De-/Activate case sensitivity for the regex search")] = False) -> None:
        """
        Print your collection (collid), document (id), pages, pagestatus, role
        Returns:
        None
        """
        load_dotenv()
        envs = dotenv_values()
        if not ts_api.valid_login():
            return
        flag = 0 if case_sensitive else re.IGNORECASE
        if len(filter_by) != len(search_term):
            print("Please provide for each filter a search term")
            return

        if not valid_filter(filter_by, search_term):
            return

        tsclient = PagePlusTranskribusUtils(*ts_api.credentials)

        with Status("Searching for documents") as status:
            try:
                cols = tsclient.list_collections()
                print(f"[bold green]Transkribus Document Search Report[/bold green] - [white]Version 1.0[/white]")
                print(f"Total collections found: {len(cols)}")
                documents = []
                total_documents = 0
                for col in cols:
                    col_id = col["colId"]
                    col_name = col["colName"]
                    total_documents += int(col["nrOfDocuments"])
                    if str_filter_not_match(filter_by, search_term, col_name, DataFilter.COLLECTION, flag) or \
                            str_filter_not_match(filter_by, search_term, col.get("role", ""), DataFilter.ROLE, flag):
                        continue
                    doc_list = tsclient.list_docs(col_id)
                    for doc in doc_list:
                        doc_id = doc["docId"]
                        if str_filter_not_match(filter_by, search_term, doc.get("title", ""), DataFilter.DOCUMENT,
                                                flag):
                            continue
                        if DataFilter.PAGE in filter_by:
                            if any(int(doc.get("nrOfPages")) < int(search_term[idx]) for idx, f in enumerate(filter_by) \
                                   if f == DataFilter.PAGE):
                                continue
                        doc_overview = tsclient.get_doc_overview_md(col_id, doc_id)
                        doc_md = doc_overview["trp_return"]["md"]
                        if DataFilter.PAGESTATUS in filter_by:
                            if not any(int(doc_md.get(f"nrOf{search_term[idx]}", -1)) != 0 for \
                                       idx, f in enumerate(filter_by) if f == DataFilter.PAGESTATUS):
                                continue
                        doc_stats = {
                            "col_id": col_id,
                            "col_name": col_name,
                            "doc_id": doc_id,
                            "doc_name": doc_md.get("title", ''),
                            "pages": doc_md.get("nrOfPages", ''),
                            "doc_md": doc_md,
                            "role": col.get("role", ''),
                        }
                        documents.append(doc_stats)
            except Exception as e:
                print(f"[red]Error occurred: {e}[/red]")
                return
        print(f"Total documents found: {total_documents}")
        print(f"Total documents matching criteria: {len(documents)}")
        table = Table(title="")
        table.add_column("Collection (COLLID)", style="green")
        table.add_column("Document (ID)", style="cyan")
        table.add_column("Pages", style="blue")
        table.add_column("PageStatus", style="steel_blue3")
        table.add_column("Role", style="cyan")
        collection = ""
        for document in documents:
            table.add_row(f"{document.get('col_name')} ({document.get('col_id')})".replace(collection, ""),
                          f"{document.get('doc_name')} ({document.get('doc_id')})",
                          f"{document.get('pages')}",
                          f"New: {document.get('doc_md').get('nrOfNew')}, "
                          f"InProgress: {document.get('doc_md').get('nrOfInProgress')}, "
                          f"Done: {document.get('doc_md').get('nrOfDone')}, "
                          f"Final: {document.get('doc_md').get('nrOfFinal')}, "
                          f"GT: {document.get('doc_md').get('nrOfGT')}",
                          f"{document.get('role')}")
            collection = f"{document.get('col_name')} ({document.get('col_id')})"
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
        if workspace in ts_workspace.names() and not overwrite_workspace:
            print(f"[red bold]Warning:[/red bold] The environment variable {workspace} already exists."
                  " Please set [green]overwrite-workspace[/green] "
                  "to True, if you want to overwrite the workspace.")
        if inputdir.is_dir():
            set_key(find_dotenv(), ts_workspace.prefix_ws + workspace, str(inputdir.absolute()))
            if loading:
                load_workspace(ts_workspace.prefix_ws + workspace)
        else:
            print(f"[red]Warning:[/red] The inputdir does not point to an existing folder.")


    @app.command(rich_help_panel="Document")
    def load_document(collection_id: Annotated[int,
                      typer.Argument(help="Collection identifier (collId).")],
                      document_id: Annotated[int,
                      typer.Argument(help="Document identifier (id).")],
                      pages: Annotated[List[int], typer.Option("--pages", "-p",
                                                               help="Page selection. If not set all pages get loaded.")] = None,
                      load_images: Annotated[bool, typer.Option(help="Store also the corresponding images")] = False,
                      folderpath: Annotated[Optional[Path], typer.Option("--folderpath", "-f",
                                                                         help="Path to store the loaded document. If "
                                                                              "not set it get stored in the workspace "
                                                                              "directory.")] = None,
                      workspace: Annotated[Optional[str], typer.Option("--workspace", "-w",
                                                                       help="Name of environmental variable, which "
                                                                            "stores the path to loaded document. The "
                                                                            "name get's appended to 'TRANSKRIBUS_WS_' and "
                                                                            "automatically cast to uppercase. E.g. "
                                                                            "new data -> TRANSKRIBUS_WS_NEW_DATA.")] = "MAIN",
                      overwrite_ws: Annotated[bool, typer.Option(help="If workspace already exists the old data gets removed."),] = False,
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
        if not ts_api.valid_login():
            return
        pages = [] if pages is None else pages
        tsclient = PagePlusTranskribusUtils(*ts_api.credentials)
        if not pages:
            pages = tsclient.get_pageIds(collection_id, document_id)
            pages = list(range(1, len(pages) + 1))
        pagedata = []
        # Download document
        with Status("Downloading document") as status:
            for page in pages:
                fulldoc_md = tsclient.get_fulldoc_md(collection_id, document_id, str(page))
                transcript = tsclient.get_transcript(fulldoc_md)
                pagedata.append((fulldoc_md, transcript))

        wsfolder = Path(tempfile.mkdtemp(prefix=ts_workspace.prefix_dir(), dir=ts_workspace.dir())) \
                   if folderpath is None else Path(folderpath)
        wsfolder.mkdir(parents=True, exist_ok=True)

        dotfile = find_dotenv()
        metadata = {ts_workspace.env: {'collection': {}}}

        for idx, (md, transcript) in enumerate(pagedata):
            doc_md = md.get('extra_info')
            if idx == 0:
                col_md = md.get('extra_info').get('collectionList').get('colList')[0]
                metadata[ts_workspace.env]['collection'].update(col_md)
                metadata[ts_workspace.env]['collection']['document'] = {}
                for key in ['docId', 'title', 'uploadTimestamp', 'uploader', 'uploaderId', 'nrOfPages', 'status']:
                    metadata[ts_workspace.env]['collection']['document'][key] = doc_md.get(key)
                metadata[ts_workspace.env]['collection']['document']['page'] = defaultdict(dict)
            page_info = metadata[ts_workspace.env]['collection']['document']['page'][md.get('page_id')]
            page_info['fileName'] = md.get('file_name')
            page_info['transcriptURL'] = md.get('transcript_url')
            page_info['timestamp'] = md.get('timestamp')
            page_info['status'] = md.get('pagestatus')
            page_info['md5Sum'] = md.get('md5sum')
            page_info['imgURL'] = md.get('img_url')
            page_info['userName'] = md.get('user')

        # Write pages
        for _, transcript in pagedata:
            with open(wsfolder.joinpath(transcript.get('file_name')), 'wb') as fout:
                fout.write(transcript['page_xml_string'])

        # Write images
        if load_images:
            with Status("Downloading images") as status:
                image_urls = [md.get('img_url') for (md, _) in pagedata]
                tsclient.save_image_urls_to_file(image_urls, wsfolder)

        # Write Metadata
        with open(wsfolder.joinpath('metadata.pageplus.json'), 'w') as meta:
            json.dump(metadata, meta, indent=4)

        # Update envs
        ws_absolute = ts_workspace.prefix_ws + workspace
        current_folder = envs.get(ws_absolute, None)
        if current_folder is not None and current_folder != '' and Path(current_folder).exists():
            if overwrite_ws:
                rmtree(current_folder)
            else:
                print(f"The data in folder {Path(current_folder).absolute()} is now unset. "
                      f"You can load it with the load local documents function.")
        set_key(dotfile, ws_absolute, str(wsfolder.absolute()))
        if loading:
            load_workspace(workspace)
        print(f"The data was successfully stored in: [bold purple]{str(wsfolder.absolute())}[/bold purple]")
        print(f"And be access via the Transkribus workspace: [bold green]{workspace}[/bold green]")


    @app.command(rich_help_panel="Document")
    def update_document(
            workspace: Annotated[
                str, typer.Argument(help="An environmental name pointing to an existing path",
                                                                  callback=validate_workspace)] = None,
            workstate: Annotated[Optional[WorkState], typer.Option('--workstate', '-s',
                                                                   help="Choose the documents inside this folder with "
                                                                        "'original', or the 'modified' scripts inside "
                                                                        "a subfolder.",
                                                                   case_sensitive=False)] = "original",
            use_metadata: Annotated[bool, typer.Option(help="Use information from metadata")] = True,
            collection_id: Annotated[int, typer.Option("--document-pk", "-d",
                                                       help="Document's primary key (pk). (Not necessary if "
                                                            "environmental is used, but can also overwrite)")] = None,
            document_id: Annotated[int, typer.Option("--document-pk", "-d",
                                                     help="Document's primary key (pk). (Not necessary if "
                                                          "environmental is used, but can also overwrite)")] = None,
            pages: Annotated[Optional[List[int]], typer.Option("--pages", "-p",
                                                               help="Page selection. If not set all pages get uploaded.")] = None,
            overwrite: Annotated[bool, typer.Option(help="Overwrite existing Transcription")] = True,
            status: Annotated[PageStatus, typer.Option("--status",
                                                       help="Page status selection.")] = None,
            note: Annotated[Optional[str], typer.Option("--note",
                                                        help="Additional information.")] = "",
            parent: Annotated[Optional[int], typer.Option("--parent",
                                                          help="Id of the parent transcription. Default: -1 (Unknown).")] = -1,
            nr_is_page_id: Annotated[Optional[bool], typer.Option("--nr-is-page-id",
                                                                  help="Set to true, if the pages variable don't contain page ids instead of page number.")] = False,
            tool_name: Annotated[Optional[str], typer.Option("--tool-name",
                                                             help="Name of the uploading tool. Default: PagePlus.")] = "PagePlus") -> None:
        """
        Uploads pages of a document to Transkribus.
        Returns:
        None
        """
        # Create a Path object for the directory
        load_dotenv()
        envs = dotenv_values()
        if not ts_api.valid_login():
            return
        # TODO: https://transkribus.eu/TrpServer/rest/collections/colID/docId/page/text

        tsclient = PagePlusTranskribusUtils(*ts_api.credentials)

        page_names = []
        if ts_workspace.prefix_ws + workspace in envs.keys():
            wsfolder = Path(envs[ts_workspace.prefix_ws + workspace])
            if use_metadata:
                metadata = json.loads(wsfolder.joinpath('metadata.pageplus.json').open('r').read())
                collection_id = metadata[ts_workspace.env]['collection']['colId']
                document_id = metadata[ts_workspace.env]['collection']['document']['docId']
                page_names = [p["fileName"] for p in metadata[ts_workspace.env]['collection']['document']['page'].values()]
                wsfolder = wsfolder.joinpath(envs.get(Environments.PAGEPLUS.as_prefix_workstate(workstate), ''))
        else:
            return
        if not pages:
            pages = sorted([file for file in wsfolder.glob('*.xml') if file.is_file() and file.name.lower not in [
                'metadata.xml', 'mets.xml']])
            pages = list(range(1, len(pages) + 1))

        with Status("Updating document") as updating_status:
            for page in pages:
                if page_names:
                    page_name = page_names[page - 1]
                else:
                    fulldoc_md = tsclient.get_fulldoc_md(collection_id, document_id, page)
                    page_name = fulldoc_md.get("fileName", "") if fulldoc_md else ""
                page_path = Path(wsfolder).joinpath(page_name)
                if page_path.is_file():
                    print(collection_id, document_id, page, overwrite,
                          status, note, parent, nr_is_page_id, tool_name)
                    tsclient.update_transcription(page_path.absolute(), collection_id, document_id, page,
                                                  overwrite, status, note, parent, nr_is_page_id, tool_name)

if (spec := util.find_spec('pageplus.utils.transkribus.transkribus_to_prima')) is None:

    @app.command()
    def install_transkribus_to_prima_converter() -> None:
        """
        If you want to use Transkribus PAGE-XML for other tools, sometimes you need to convert their version into
        the official, current PRIMA version.
        This Converter uses parts of https://github.com/kba/transkribus-to-prima/ by Konstantin Baierer (kba)
        """

        url = 'https://raw.githubusercontent.com/kba/transkribus-to-prima/master/transkribus_to_prima/convert.py'
        output_filename = Path(__file__).resolve().parent.parent.joinpath('utils/transkribus/transkribus_to_prima.py')
        response = requests.get(url)
        if response.status_code == 200:
            with open(output_filename, 'wb') as file:
                file.write(response.content)
            print(f"[green]File downloaded successfully: {output_filename}[/green]")
        else:
            print(f"[red]Failed to download file. Status code: {response.status_code}[/red]")

else:

    class ConvertOptions(str, Enum):
        """
        Level of transkribus data
        """
        ALL = "All"
        METADATA = "Metadata"
        TABLE = "Table"
        TEXTEQUIV = "Text"
        READING_ORDER = "Reading-Order"
        IMAGE_TRANSFORM = "Images"
        TAG_PROPERTY_LINK = "Tags"


    @app.command(rich_help_panel="Document")
    def to_prima(workspace: Annotated[str, typer.Argument(help="Environmental name pointing to an existing path",
                            callback=validate_workspace)] = None,
                 workstate: Annotated[Optional[WorkState],
                            typer.Option('--workstate', '-s',
                                          help="Choose the documents inside this folder with "
                                          "'original', or the 'modified' scripts inside the subfolder.",
                                           case_sensitive=False)] = "original",
                 overwrite: Annotated[bool, typer.Option(help="Overwrite existing Transcription")] = True,
                 convert: Annotated[
                     ConvertOptions, typer.Option(help="Convert options (recommended just convert all)")] = "All",
                 outputdir: Annotated[Path, typer.Option('--outputdir', '-o',
                                                         help=f"Path to the output directory where "
                                                              f"the text files will be saved")] = None) -> None:
        """
        If you want to use Transkribus PAGE-XML for other tools, sometimes you need to convert their version into
        the official, current PRIMA version.
        This Converter uses parts of https://github.com/kba/transkribus-to-prima/ by Konstantin Baierer (kba)
        """
        from pageplus.utils.transkribus.transkribus_to_prima import TranskribusToPrima
        from pageplus.utils.fs import collect_xml_files
        from pageplus.io.parser import parse_xml
        from pageplus.io.writer import write_xml

        load_dotenv()
        envs = dotenv_values()
        wsfolder = Path(get_key(find_dotenv(), ts_workspace.prefix_ws + workspace)).joinpath(
            envs.get(Environments.PAGEPLUS.as_prefix_workstate(workstate), ''))
        outputdir = wsfolder if overwrite else Path(outputdir)
        outputdir.mkdir(parents=True, exist_ok=True)
        if wsfolder.exists() and outputdir is not None:
            with Status("Translating from Transkribus variant of PAGE to standard-conformant PAGE") as status:
                for xml_file in collect_xml_files(iter([wsfolder])):
                    tree = parse_xml(xml_file)[0]
                    ttp = TranskribusToPrima(tree)
                    ttp.convert_metadata() if convert.ALL or convert.METADATA else None
                    ttp.convert_table() if convert.ALL or convert.TABLE else None
                    ttp.convert_textequiv() if convert.ALL or convert.TEXTEQUIV else None
                    ttp.convert_reading_order() if convert.ALL or convert.READING_ORDER else None
                    ttp.convert_image_transform() if convert.ALL or convert.IMAGE_TRANSFORM else None
                    ttp.convert_tag_property_link() if convert.ALL or convert.TAG_PROPERTY_LINK else None
                    write_xml(ttp, outputdir / xml_file.name)
                    print(f"[gold1 bold]{xml_file.name}[/gold1 bold][dark_goldenrod] "
                          f"converted into standard-conformant PAGE![/dark_goldenrod]")

if __name__ == "__main__":
    app()
