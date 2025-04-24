from dataclasses import dataclass
from importlib import util

import requests
import typer
from dotenv import find_dotenv, get_key, set_key
from rich import print
from rich.table import Table
from typing_extensions import Annotated

from pageplus.utils.api import API
from pageplus.utils.constants import Environments, LLMProvider

if (spec := util.find_spec('litellm')) is not None:
    import litellm

    @dataclass
    class LLMAPI(API):
        environment: Environments = Environments.PAGEPLUS
        keep_alive_time = 60.0

        @property
        def llmprovider(self):
            return LLMProvider[self.provider.split('__')[0]]

        def check_valid_key(self):
            """
            Checks if api key is valid
            """
            print('[green]Valid API key[green]') if litellm.check_valid_key(self.model, self.api_key) \
                else print('[red]Not a valid API key[red]')

        @property
        def model_with_prefix(self):
            return '' if self.model == '' else (self.llmprovider.name.lower()+'/'+self.model)

        @property
        def model(self, prefix=False) -> str:
            """
            Set model
            Returns:
            None
            """
            modelname = get_key(find_dotenv(), self.environment.as_prefix()+self.prefix_provider()+'MODEL')
            modelname = modelname if modelname else ''
            if prefix and modelname != '':
                modelname = self.llmprovider.name.lower()
            return modelname if modelname else ''


        @model.setter
        def model(self, modelname: Annotated[str, typer.Argument(help="Provider")]) -> None:
            """
            Get current model
            Returns:
            None
            """
            try:
                assert self.check_model(modelname)
                set_key(find_dotenv(), self.environment.as_prefix()+self.prefix_provider()+'MODEL', modelname)
                print(f"[green]Model updated successfully to:[/green] {self.model}")
            except Exception as e:
                print(f"[red]Failed to update the current model:[/red] {self.model}")


        def check_model(self, modelname: str) -> bool:
            """
            Check if model is compatible with the current provider selection list
            Returns:
            None
            """
            response = requests.get(f"{self.api_base_url}/models", headers={"Authorization": f"Bearer {self.api_key}"})
            response.raise_for_status()
            response = response.json()
            modellist = [model['id'] for model in response['data']]
            if modellist is None:
                print(f"[ModelCheck] [orange]No model selection available for provider {self.llmprovider.value}.[/orange]")
                return True
            elif modelname in modellist:
                print(f"[ModelCheck] [green]Model exists in provider {self.llmprovider.value} model selection.[/green]")
                return True
            else:
                print(f"[ModelCheck] [red]Model is not in selection options for {self.llmprovider.value}.[/red]")
                return False

        def show_models(self):
            """
            Print modelloptions for the current provider
            Returns:
            None
            """
            response = requests.get(f"{self.api_base_url}/models", headers={"Authorization": f"Bearer {self.api_key}"})
            response.raise_for_status()
            response =  response.json()
            modellist = response['data']
            if modellist:
                print(f"[green]Available models for provider {self.provider.replace('__',' - ')}[/green]")
                table = Table(title=f"[green]Models overview[/green]")
                table.add_column(f"Provider", justify="right", style="cyan", no_wrap=True)
                table.add_column("Model")
                table.add_row(self.provider.replace('__',' - '),
                              '\n'.join([model['id'] for model in modellist]))
                print(table)

if (spec := util.find_spec('google')) is not None:
    from google import genai
    from google.genai.errors import ClientError

    @dataclass
    class GEMINIAPI(API):
        environment: Environments = Environments.PAGEPLUS
        keep_alive_time = 60.0

        @property
        def llmprovider(self):
            return LLMProvider['GEMINI']

        @property
        def provider(self) -> str:
            return ''

        def base_url(self) -> str:
            """
            Write the URL of the environment instance (e.g. https://www.escriptorium.fr) to the .env file
            Returns:
            None
            """
            return 'https://generativelanguage.googleapis.com/v1beta/'

        def api_base_url(self) -> str:
            """
            Write the URL of the environment instance (e.g. https://www.escriptorium.fr) to the .env file
            Returns:
            None
            """
            return 'https://generativelanguage.googleapis.com/v1beta/'

        def client(self) -> genai.Client:
            """
            Write the URL of the environment instance (e.g. https://www.escriptorium.fr) to the .env file
            Returns:
            None
            """
            if self.project:
                return genai.Client(api_key=self.api_key, project=self.project)
            return genai.Client(api_key=self.api_key)

        @property
        def project(self):
            return None#self.project

        def check_valid_key(self):
            """
            Checks if api key is valid
            """
            print('[green]Valid API key[green]') if litellm.check_valid_key(self.model, self.api_key) \
                else print('[red]Not a valid API key[red]')

        @property
        def model(self, prefix=False) -> str:
            """
            Set model
            Returns:
            None
            """
            modelname = get_key(find_dotenv(), self.environment.as_prefix()+self.prefix_provider()+'MODEL')
            modelname = modelname if modelname else ''
            if prefix and modelname != '':
                modelname = self.llmprovider.name.lower()
            return modelname if modelname else ''


        @model.setter
        def model(self, modelname: Annotated[str, typer.Argument(help="Provider")]) -> None:
            """
            Get current model
            Returns:
            None
            """
            try:
                assert self.check_model(modelname)
                set_key(find_dotenv(), self.environment.as_prefix()+self.prefix_provider()+'MODEL', modelname)
                print(f"[green]Model updated successfully to:[/green] {self.model}")
            except Exception as e:
                print(f"[red]Failed to update the current model:[/red] {self.model}")


        def check_model(self, model: str) -> bool:
            """
            Check if model is compatible with the current provider selection list
            Returns:
            None
            """
            try:
                self.client().models.get(model=model)
                print(f"[ModelCheck] [green]{model} exists.[/green]")
                return True
            except ClientError as e:
                print(f"{e.message}")
                print(f"[ModelCheck] [red]{model} does not exists.[/red]")
                return False


        def show_models(self):
            """
            Print modelloptions for the current provider
            Returns:
            None
            """
            modellist = self.client().models.list()
            print(modellist.page_size)
            if modellist:
                print(f"[green]Available models for provider {self.provider.replace('__',' - ')}[/green]")
                table = Table(title=f"[green]Models overview[/green]")
                table.add_column(f"Provider", justify="right", style="cyan", no_wrap=True)
                table.add_column("Model")
                table.add_row(self.provider.replace('__',' - '),
                              '\n'.join([model.name for model in modellist]))
                print(table)

        def show_modeldetails(self, model: str):
            """
            Print modelloptions for the current provider
            Returns:
            None
            """
            try:
                model = self.client().models.get(model=model)
                print(model)
            except ClientError as e:
                print(f"{e.message}")
                pass


