from dataclasses import dataclass, field

import typer
from dotenv import dotenv_values, get_key, set_key
from rich import print
from rich.table import Table
from typing_extensions import Annotated

from pageplus.utils.constants import Environments, Provider
from pageplus.utils.envs import filter_dotenv, get_env_path


@dataclass
class API:
    environment: Environments = Environments.PAGEPLUS
    env_value: str = field(init=False)
    env_prefix: str = field(init=False)
    prefix_ws: str = field(init=False)
    prefix_loaded_ws: str = field(init=False)

    def __post_init__(self):
        self.env = self.environment.value
        self.prefix = self.environment.as_prefix()
        self.prefix_ws = self.environment.as_prefix_workspace()
        self.prefix_loaded_ws = self.environment.as_prefix_loaded_workspace()

    def prefix_provider(self):
        """
        Get provider prefix
        Returns:
        None
        """
        return (self.provider + '_').lstrip('_')

    @property
    def provider(self) -> str:
        """
        Get provider
        Returns:
        None
        """
        providername = get_key(
            get_env_path(),
            self.environment.name.upper() +
            "_PROVIDER")
        return providername if providername else ''

    @provider.setter
    def provider(self,
                 providername: Annotated[Provider,
                                         typer.Argument(help="Provider and service name")],
                 service: Annotated[str,
                                    typer.Argument(help="Service")] = "DEFAULT") -> None:
        """
        Set provider
        Returns:
        None
        """
        try:
            provider = providername.name.upper() + '__' + service.upper()
            set_key(
                get_env_path(),
                self.environment.name.upper() +
                "_PROVIDER",
                provider)
            print("[green]The provider updated successfully.[green]")
        except Exception as e:
            print(f"[red]Failed to update the provider: {e}[red]")

    @property
    def base_url(self) -> str:
        """
        Write the URL of the environment instance (e.g. https://www.escriptorium.fr) to the .env file
        Returns:
        None
        """
        return get_key(
            get_env_path(),
            self.prefix +
            self.prefix_provider() +
            "BASE_URL")

    @base_url.setter
    def base_url(self, url: Annotated[str, typer.Argument(
            help="URL to the service")]) -> None:
        """
        Write the URL of the environment instance (e.g. https://www.escriptorium.fr) to the .env file
        Returns:
        None
        """
        try:
            set_key(
                get_env_path(),
                self.prefix +
                self.prefix_provider() +
                "BASE_URL",
                url)
            print("[green]The url updated successfully.[green]")
        except Exception as e:
            print(f"[red]Failed to update the url: {e}[red]")

    @property
    def credentials(self) -> tuple[str, str]:
        """
        Get the credentials
        Returns:
        None
        """
        dotfile = get_env_path()
        name = get_key(
            dotfile, f"{self.prefix + self.prefix_provider()}USERNAME")
        password = get_key(
            dotfile, f"{self.prefix + self.prefix_provider()}PASSWORD")
        return name, password

    @credentials.setter
    def credentials(self, credentials: tuple) -> None:
        """
        Set your credentials to the .env file
        Returns:
        None
        """
        try:
            dotfile = get_env_path()
            set_key(dotfile,
                    f"{self.prefix + self.prefix_provider()}USERNAME",
                    credentials[0])
            set_key(dotfile,
                    f"{self.prefix + self.prefix_provider()}PASSWORD",
                    credentials[1])
            print("[green]Credentials updated successfully.[green]")
        except Exception as e:
            print(f"[red]Failed to update credentials: {e}[red]")

    @property
    def api_base_url(self) -> str:
        """
        Get api base url
        WARNING: Currently
        Returns:
        str
        """
        dotfile = get_env_path()
        return get_key(
            dotfile,
            self.prefix +
            self.prefix_provider() +
            "API_BASE")

    @api_base_url.setter
    def api_base_url(self, url: str) -> None:
        """
        Set if api url differs from base-url/api and api-key should be used
        WARNING: Currently
        Returns:
        None
        """
        dotfile = get_env_path()
        set_key(
            dotfile,
            self.prefix +
            self.prefix_provider() +
            "API_BASE",
            url)
        print("[green]Base URL for the API was updated successfully.[green]")

    @property
    def api_key(self) -> str:
        """
        Get the API key for the environment (only used if name and password is not set).
        Returns:
        str
        """
        dotfile = get_env_path()
        return get_key(
            dotfile,
            self.prefix +
            self.prefix_provider() +
            "API_KEY")

    @api_key.setter
    def api_key(self, key: str) -> None:
        """
        Set the API key for the environment (only used if name and password is not set).
        Returns:
        None
        """
        dotfile = get_env_path()
        set_key(dotfile, self.prefix + self.prefix_provider() + "API_KEY", key)
        print("[green]The API key updated successfully.[green]")

    def valid_login(self) -> bool:
        envs = dotenv_values()
        check = all(
            [self.base_url,
             self.credentials[0],
             self.credentials[1]])
        check_api = all([self.api_key, self.api_base_url])
        if not check and not check_api:
            print(
                "[red bold]Missing login information:[/red bold] [red]Ensure that the URL, username, and password or "
                "API URL and key are correctly configured.[/red]")
            return False
        return True

    def show_settings(self) -> None:
        """
        Print your current settings from the .env file
        Returns:
        None
        """
        table = Table(title=f"[green]{self.env} settings[/green]")
        table.add_column(
            "Setting",
            justify="right",
            style="cyan",
            no_wrap=True)
        table.add_column("Value")
        [table.add_row(var.replace(self.prefix + self.prefix_provider(), ''), key) if
         var != self.prefix + self.prefix_provider() + "PASSWORD" else
         table.add_row(var.replace(self.prefix + self.prefix_provider(), ''), key[:3] + '***') for
         (var, key) in filter_dotenv(self.prefix + self.prefix_provider()).items() if not
         (var.startswith(self.prefix_ws) or var.startswith(self.prefix_loaded_ws) or var.replace(self.prefix + self.prefix_provider(), '').startswith('_'))]
        print(table)

@dataclass
class EscriptoriumAPI(API):
    environment: Environments = Environments.ESCRIPTORIUM

    def __post_init__(self):
        self.env = self.environment.value
        self.prefix = self.environment.as_prefix()
        self.prefix_ws = self.environment.as_prefix_workspace()
        self.prefix_loaded_ws = self.environment.as_prefix_loaded_workspace()

    @property
    def instance_name(self) -> str:
        """
        Name of actual instance
        Returns:
        None
        """
        return get_key(
            get_env_path(),
            self.prefix +
            self.prefix_provider() +
            "INSTANCE_NAME")

    @instance_name.setter
    def instance_name(self, url: Annotated[str, typer.Argument(
            help="URL to eScriptorium")]) -> None:
        """
        Name of actual instance
        Returns:
        None
        """
        try:
            set_key(
                get_env_path(),
                self.prefix +
                self.prefix_provider() +
                "INSTANCE_NAME",
                url)
            print("[green]The instance name updated successfully.[green]")
        except Exception as e:
            print(f"[red]Failed to update the instance name: {e}[red]")

    @property
    def document_pk(self) -> int:
        """
        ID of the document
        Returns:
        None
        """
        return get_key(
            get_env_path(),
            self.prefix +
            self.prefix_provider() +
            "DOCUMENT_PK")

    @document_pk.setter
    def document_pk(self, url: Annotated[str, typer.Argument(
            help="Document pk")]) -> None:
        """
        ID of the document
        Returns:
        None
        """
        try:
            set_key(
                get_env_path(),
                self.prefix +
                self.prefix_provider() +
                "DOCUMENT_PK",
                url)
            print("[green]The document pk updated successfully.[green]")
        except Exception as e:
            print(f"[red]Failed to update the document pk: {e}[red]")


    @property
    def transcription_pk(self) -> int:
        """
        ID of the transcription
        Returns:
        None
        """
        return get_key(
            get_env_path(),
            self.prefix +
            self.prefix_provider() +
            "TRANSCRIPTION_PK")

    @transcription_pk.setter
    def transcription_pk(self, url: Annotated[str, typer.Argument(
            help="Transcription pk")]) -> None:
        """
        ID of the transcription
        Returns:
        None
        """
        try:
            set_key(
                get_env_path(),
                self.prefix +
                self.prefix_provider() +
                "TRANSCRIPTION_PK",
                url)
            print("[green]The transcription pk updated successfully.[green]")
        except Exception as e:
            print(f"[red]Failed to update the transcription pk: {e}[red]")


@dataclass
class TranskribusAPI(API):
    environment: Environments = Environments.ESCRIPTORIUM

    def __post_init__(self):
        self.env = self.environment.value
        self.prefix = self.environment.as_prefix()
        self.prefix_ws = self.environment.as_prefix_workspace()
        self.prefix_loaded_ws = self.environment.as_prefix_loaded_workspace()


    @property
    def provider(self) -> str:
        """
        Get provider
        Returns:
        None
        """
        return ''

    @property
    def base_url(self) -> str:
        """
        Get  base url
        WARNING: Currently
        Returns:
        str
        """
        dotfile = get_env_path()
        key = get_key(
            dotfile,
            self.prefix +
            self.prefix_provider() +
            "BASE_URL")
        return key if key else "https://transkribus.eu/TrpServer/rest"

    @base_url.setter
    def base_url(self, url: str) -> None:
        """
        Set if url differs from api and api-key should be used
        WARNING: Currently
        Returns:
        None
        """
        dotfile = get_env_path()
        set_key(
            dotfile,
            self.prefix +
            self.prefix_provider() +
            "BASE_URL",
            url)
        print("[green]Base URL for the API was updated successfully.[green]")


    @property
    def api_base_url(self) -> str:
        """
        Get api base url
        WARNING: Currently
        Returns:
        str
        """
        dotfile = get_env_path()
        key = get_key(
            dotfile,
            self.prefix +
            self.prefix_provider() +
            "API_BASE")
        return key if key else "https://transkribus.eu/TrpServer/rest"

    @api_base_url.setter
    def api_base_url(self, url: str) -> None:
        """
        Set if api url differs from base-url/api and api-key should be used
        WARNING: Currently
        Returns:
        None
        """
        dotfile = get_env_path()
        set_key(
            dotfile,
            self.prefix +
            self.prefix_provider() +
            "API_BASE",
            url)
        print("[green]Base URL for the API was updated successfully.[green]")

    @property
    def document_id(self) -> int:
        """
        ID of the document
        Returns:
        None
        """
        return get_key(
            get_env_path(),
            self.prefix +
            self.prefix_provider() +
            "DOCUMENT_ID")

    @document_id.setter
    def document_id(self, url: Annotated[str, typer.Argument(
            help="Document id")]) -> None:
        """
        ID of the document
        Returns:
        None
        """
        try:
            set_key(
                get_env_path(),
                self.prefix +
                self.prefix_provider() +
                "DOCUMENT_ID",
                url)
            print("[green]The document pk updated successfully.[green]")
        except Exception as e:
            print(f"[red]Failed to update the document pk: {e}[red]")


    @property
    def transcription_id(self) -> int:
        """
        ID of the transcription
        Returns:
        None
        """
        return get_key(
            get_env_path(),
            self.prefix +
            self.prefix_provider() +
            "TRANSCRIPTION_ID")

    @transcription_id.setter
    def transcription_id(self, url: Annotated[str, typer.Argument(
            help="Transcription id")]) -> None:
        """
        ID of the transcription
        Returns:
        None
        """
        try:
            set_key(
                get_env_path(),
                self.prefix +
                self.prefix_provider() +
                "TRANSCRIPTION_ID",
                url)
            print("[green]The transcription pk updated successfully.[green]")
        except Exception as e:
            print(f"[red]Failed to update the transcription pk: {e}[red]")