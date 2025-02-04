from dataclasses import dataclass
from importlib import util

import typer
from rich import print
from rich.table import Table
from typing_extensions import Annotated

from dotenv import find_dotenv, get_key, dotenv_values, set_key

from pageplus.utils.constants import Environments, LLMProvider
from pageplus.utils.api import API


if (spec := util.find_spec('litellm')) is not None:
    import litellm
    import requests

    @dataclass
    class LLMAPI(API):
        environment: Environments = Environments.PAGEPLUS
        keep_alive_time = 60.0

        def llmprovider(self):
            return LLMProvider[self.provider]

        def check_valid_key(self):
            """
            Checks if api key is valid
            """
            print('[green]Valid API key[green]') if litellm.check_valid_key(self.model, self.api_key) \
                else print('[red]Not a valid API key[red]')

        @property
        def model_with_prefix(self):
            return '' if self.model == '' else (
                    self.llmprovider().lower()+'/'+self.model)

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
                modelname = self.llmprovider().lower().replace('_01','').replace('_02','').replace('_03','')
            return modelname if modelname else ''


        @model.setter
        def model(self, modelname: Annotated[str, typer.Argument(help="Provider")]) -> None:
            """
            Get current model
            Returns:
            None
            """
            try:
                self.check_model(modelname)
                set_key(find_dotenv(), self.environment.as_prefix()+self.prefix_provider()+'MODEL', modelname)
                print("[green]Model updated successfully.[green]")
            except Exception as e:
                print(f"[red]Failed to update the model: {e}[red]")


        def check_model(self, modelname: str) -> None:
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
                print(f"[ModelCheck] [orange]No model selection available for provider {self.llmprovider().value}.[/orange]")
            elif modelname in modellist:
                print(f"[ModelCheck] [green]Model exists in provider {self.llmprovider().value} model selection.[/green]")
            else:
                print(f"[ModelCheck] [red]Model is not in selection options for {self.llmprovider().value}.[/red]")

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
            print(modellist)
            if modellist:
                print(f"[green]Available models for provider {self.llmprovider().value}[/green]")
                table = Table(title=f"[green]Models overview[/green]")
                table.add_column(f"Provider", justify="right", style="cyan", no_wrap=True)
                table.add_column("Model")
                table.add_row(LLMProvider[self.provider].value, '\n'.join([model['id'] for model in modellist]))
                print(table)
