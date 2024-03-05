from dataclasses import dataclass, field

import typer
from rich import print
from rich.table import Table
from typing_extensions import Annotated

from dotenv import find_dotenv, get_key, dotenv_values, set_key

from pageplus.utils.constants import Environments
from pageplus.utils.envs import filter_envs


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

    @property
    def url(self) -> str:
        """
        Write the URL of the environment instance (e.g. https://www.escriptorium.fr) to the .env file
        Returns:
        None
        """
        return get_key(find_dotenv(), self.prefix + "URL")

    @url.setter
    def url(self, url: Annotated[str, typer.Argument(help="URL to eScriptorium")]) -> None:
        """
        Write the URL of the environment instance (e.g. https://www.escriptorium.fr) to the .env file
        Returns:
        None
        """
        try:
            dotfile = find_dotenv()
            set_key(dotfile, self.prefix + "URL", url)
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
        dotfile = find_dotenv()
        name = get_key(dotfile, f"{self.prefix}USERNAME")
        password = get_key(dotfile, f"{self.prefix}PASSWORD")
        return name, password

    @credentials.setter
    def credentials(self, credentials: tuple) -> None:
        """
        Set your credentials to the .env file
        Returns:
        None
        """
        try:
            dotfile = find_dotenv()
            set_key(dotfile, f"{self.prefix}USERNAME", credentials[0])
            set_key(dotfile, f"{self.prefix}PASSWORD", credentials[1])
            print("[green]Credentials updated successfully.[green]")
        except Exception as e:
            print(f"[red]Failed to update credentials: {e}[red]")

    @property
    def api_url(self) -> str:
        """
        Get api url
        WARNING: Currently
        Returns:
        str
        """
        dotfile = find_dotenv()
        return get_key(dotfile, self.prefix + "API_URL")

    @api_url.setter
    def api_url(self, url: str) -> None:
        """
        Set if api url differs from base-url/api and api-key should be used
        WARNING: Currently
        Returns:
        None
        """
        dotfile = find_dotenv()
        set_key(dotfile, self.prefix + "API_URL", url)

    @property
    def api_key(self) -> str:
        """
        Get the API key for the environment (only used if name and password is not set).
        Returns:
        str
        """
        dotfile = find_dotenv()
        return get_key(dotfile, self.prefix + "API_KEY")

    @api_key.setter
    def api_key(self, key: str) -> None:
        """
        Set the API key for the environment (only used if name and password is not set).
        Returns:
        None
        """
        dotfile = find_dotenv()
        set_key(dotfile, self.prefix + "API_KEY", key)

    def valid_login(self) -> bool:
        envs = dotenv_values()
        check = all(
            [envs.get(self.prefix + 'URL', None),
             envs.get(self.prefix + 'USERNAME', None),
             envs.get(self.prefix + 'PASSWORD', None)])
        check_api = all([envs.get(self.prefix + 'API_KEY', None),
                         any([envs.get(self.prefix + 'URL', None),
                              envs.get(self.prefix + 'API_URL', None)])])
        if not check and not check_api:
            print(
                f"[red bold]Missing login information:[/red bold] [red]Ensure that the URL, username, and password or "
                f"API URL and key are correctly configured.[/red]")
            return False
        return True

    def show_settings(self) -> None:
        """
        Print your current settings from the .env file
        Returns:
        None
        """
        table = Table(title=f"[green]{self.env} settings[/green]")
        table.add_column("Setting", justify="right", style="cyan", no_wrap=True)
        table.add_column("Value")
        [table.add_row(var.replace(self.prefix, ''), key) if var != self.prefix+"PASSWORD" else
         table.add_row(var.replace(self.prefix, ''), key[:3] + '***') for
         (var, key) in filter_envs(self.prefix).items() if not
         (var.startswith(self.prefix_ws) or var.startswith(self.prefix_loaded_ws))]
        print(table)
