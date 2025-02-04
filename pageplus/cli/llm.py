import json
import subprocess
import sys
from importlib import util
from pathlib import Path
from typing import List, Annotated

import typer
from dotenv import set_key, find_dotenv
from rich import print

from pageplus.models.page import Page
from pageplus.utils.fs import collect_xml_files, find_image
from pageplus.utils.fs import transform_inputs
from pageplus.utils.image import image_to_base64, get_image, crop_image_by_polygon
from pageplus.io.logger import logging

app = typer.Typer()


def _install() -> None:
    """
    Before llm can be used, please use this install command
    to install litellm!
    """
    subprocess.check_call([sys.executable, "-m", "pip", "install", "-I", "litellm"])


if (spec := util.find_spec('litellm')) is None:

    @app.command()
    def install() -> None:
        """
        Before llm can be used, please use this install command
        to install litellm!
        """
        _install()
        set_key(find_dotenv(), Environments.LLM.name.upper() + "_PROVIDER", "OPENAI")

else:

    from pageplus.utils.constants import Environments, LLMProvider
    from pageplus.utils.workspace import Workspace
    from pageplus.utils.llm.api import LLMAPI

    from litellm import completion

    llm_workspace = Workspace(Environments.LLM)
    llm_api = LLMAPI(Environments.LLM)


    ### PACKAGE ###
    @app.command(rich_help_panel="Package")
    def update_package() -> None:
        """
        Updates litellm by the BerriAI team!
        """
        _install()


    ### SETTINGS ###
    @app.command(rich_help_panel="Settings")
    def set_provider(provider: Annotated[LLMProvider, typer.Argument(help="LiteLLM Provider")] = "OpenAI",
                     service: Annotated[str, typer.Argument(help="Service")] = None) -> None:
        """
        Set provider for LiteLLM (Default: OpenAI)
        Returns:
        None
        """
        llm_api.__class__.provider.fset(llm_api, provider, service)


    @app.command(rich_help_panel="Settings")
    def set_api_base_url(url: Annotated[str, typer.Argument(help="URL to LLM")]) -> None:
        """
        Write the URL of the provider instance
        Returns:
        None
        """
        llm_api.api_base_url = url


    @app.command(rich_help_panel="Settings")
    def set_api_key(api_key: Annotated[str, typer.Argument(help="API Key for the provider")]) -> None:
        """
        Set the API Key for the provider
        Returns:
        None
        """
        llm_api.api_key = api_key


    @app.command(rich_help_panel="Settings")
    def show_settings() -> None:
        """
        Print your current settings from the .env file
        Returns:
        None
        """
        llm_api.show_settings()


    @app.command()
    def check_valid_key() -> None:
        llm_api.check_valid_key()


    ### MODELS ###
    @app.command()
    def show_models() -> None:
        llm_api.show_models()


    @app.command()
    def check_model(model: Annotated[str, typer.Argument(help="Set model for LLM Provider")]) -> None:
        llm_api.check_model(model)


    @app.command()
    def set_model(model: Annotated[str, typer.Argument(help="Set model for LLM Provider")]) -> None:
        llm_api.model = model


    ### DOCUMENTS ###
    @app.command()
    def spellcheck_lines(inputs: Annotated[List[str],
    typer.Argument(exists=True, help="Paths to the XML files to be checked.", callback=transform_inputs)] = None,
                         add_fulltext: Annotated[bool, typer.Option(
                             help="Add the fulltext of the page as additional information to the prompt")] = False):
        """
        Check the spelling in existing llm's
        """
        import re
        def fix_missing_commas(json_str):
            """
            A heuristic approach to fix missing commas in JSON.

            This function looks for a pattern where a closing quote or bracket is immediately
            followed by whitespace and then an opening quote (which likely indicates a missing comma).
            It inserts a comma between them.

            Note: This is not a complete JSON fixer but may help in cases where the only error is a missing delimiter.
            """
            # This pattern finds a closing quote (") or closing curly brace (}) or closing square bracket (])
            # that is directly followed by whitespace and then an opening quote (") or opening curly brace ({)
            # and inserts a comma between them.
            pattern = r'([}\]"])\\s*(?=["{])'

            # The replacement string: add a comma after the matched character.
            fixed_str = re.sub(pattern, r'\1,', json_str)

            # An additional heuristic: sometimes a missing comma between key/value pairs in an object can be fixed by:
            # Looking for a pattern like:
            #     "key": "value"  "next_key":
            # and inserting a comma between the string and the next key.
            pattern2 = r'(")\s*(")'
            fixed_str = re.sub(pattern2, r'\1, \2', fixed_str)

            return fixed_str

        def call_llm(input_data, fulltext):
            # Create the prompt text that instructs the model what to do
            prompt = f"""
                                    You are a spellchecker. Given the following JSON object containing lines with 'lineid' and 'original', 
                                    please correct any spelling mistakes in each 'original' and return a JSON object with a new item added 'corrected'
                                    The resulting JSON have to contain always! both 'original' and 'corrected'.

                                    This is the fulltext of page, as additional information:
                                    {fulltext if add_fulltext else ''}
                                    
                                    Input JSON:
                                    {json.dumps(input_data, indent=2)}

                                    Output JSON:
                                    """
            # print(prompt)
            try:
                response = completion(
                    model=llm_api.model_with_prefix,
                    api_base=llm_api.api_base_url,
                    api_key=llm_api.api_key,
                    timeout=60.0,
                    stream=False,
                    temperature=0,
                    top_p=0,
                    n=1,  # Generate 1 response
                    messages=[
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": prompt},
                            ]
                        }
                    ],
                    response_format={
                        'type': 'json_object'
                    },
                    max_tokens=8192,
                )
            except Exception as e:
                print("An error occurred during completion:", e)
                return {}
            print(response.choices[0].message.content)
            # Extract the JSON string from the response. Adjust indices if necessary.
            json_str = response.choices[0].message.content
            print(json_str)
            # First, try to load the malformed JSON to see the error
            try:
                data_dict = json.loads(json_str)
            except json.JSONDecodeError as e:
                print("Initial JSON decode error:", e)
                # Attempt to fix the JSON by inserting missing commas
                fixed_json = fix_missing_commas(json_str)
                print("Fixed JSON attempt:\n", fixed_json)
                try:
                    data_dict = json.loads(fixed_json)
                    print("Successfully loaded JSON after fixing.")
                except json.JSONDecodeError as e2:
                    print("Still failed to decode JSON:", e2)
                    data_dict = {}
            return data_dict

        xml_files = collect_xml_files(map(Path, inputs))
        # Raise error if no xml files are found
        if not xml_files:
            raise FileNotFoundError('No xml files found in input directory')
        for xml_file in xml_files:
            print(xml_file)
            page = Page(xml_file)
            fulltext = page.extract_fulltext()
            corrected_lines = {'lines': {}}
            for textregion in page.regions.textregions:
                text_dict = {"lines": {}}
                for line in textregion.textlines:
                    text = line.get_text()
                    text_dict['lines'][line.get_id()] = {"original": text if text else ''}
                    if len(text_dict['lines']) > 10:
                        corrected_lines['lines'].update(call_llm(text_dict['lines'], fulltext))
                        text_dict = {"lines": {}}
                if len(text_dict['lines']) > 0:
                    corrected_lines['lines'].update(call_llm(text_dict['lines'], fulltext))
            # Save corrected lines to XML
            with xml_file.with_suffix('.spellchecked.json').open('w', encoding='utf-8') as fout:
                json.dump(corrected_lines, fout, indent=2, ensure_ascii=False)


    @app.command()
    def spellcheck_fulltext(inputs: Annotated[List[str],
    typer.Argument(exists=True, help="Paths to the XML files to be checked.", callback=transform_inputs)] = None):
        """
        Check the spelling in existing llm's
        """
        xml_files = collect_xml_files(map(Path, inputs))
        # Raise error if no xml files are found
        if not xml_files:
            raise FileNotFoundError('No xml files found in input directory')
        for xml_file in xml_files:
            print(xml_file)
            page = Page(xml_file)
            fulltext = page.extract_fulltext()
            prompt = f"""
            You are an expert in spellchecking. Given the following fulltext. Analyse the fulltext and find all possible
            OCR errors and missspelling. Please write out our findings numbered in the following manner: 
            
            1.
            Original Text: ...
            Corrected Text: ...
            ..
            
            
            Here is the fulltext to analyze:
            {fulltext}
            
            """
            try:
                response = completion(
                    model=llm_api.model_with_prefix,
                    api_base=llm_api.api_base_url,
                    api_key=llm_api.api_key,
                    timeout=60.0,
                    stream=False,
                    temperature=0,
                    top_p=0,
                    n=1,  # Generate 1 response
                    messages=[
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": prompt},
                            ]
                        }
                    ],
                    max_tokens=8192,
                )
                answer = response.choices[0].message.content
                print(answer)

                # Save corrected lines to XML
                with xml_file.with_suffix('.spellchecked.text').open('w', encoding='utf-8') as fout:
                    fout.write(answer)

            except Exception as e:
                print("An error occurred during completion:", e)


    @app.command()
    def ocr(inputs: Annotated[List[str],
    typer.Argument(exists=True, help="Paths to the XML files to be checked.", callback=transform_inputs)] = None,
            image_folder: Annotated[str, typer.Argument(exists=True,
                                                        help="Folder to the images relative to page-xml (default same as input)")] = '.',
            same_names: Annotated[bool, typer.Option(
                help="Use the page-xml filename to search for the image (default use imageFilename from pagexml file)")] = False,
            image_extension: Annotated[str, typer.Option(
                help="Filename extension of the images (only active with 'same_names' option)")] = '.jpg',
            save_snippets: Annotated[bool, typer.Option(help="Save snippets (debug option)")] = False,
            dry_run: Annotated[bool, typer.Option(help="If True, the function will not write any files.")] = False):
        """
        OCR with the exisiting layout information. Existing text will be overwritten.
        """
        # API details
        prompt = ("You are an expert in recognizing text in an image, without modify the results."
                  "It is not allowed to additional characters. Keep line breaks and hyphens."
                  "Recognize the text in the images: word by word! No explanation, no newlines, with punctuations."
                  "Output format (a single line with the information):"
                  "This text was on the image.")
        # Read XML
        xml_files = collect_xml_files(map(Path, inputs))
        # Raise error if no xml files are found
        if not xml_files:
            raise FileNotFoundError('No xml files found in input directory')
        for xml_file in xml_files:
            print(xml_file)
            # Read XML content
            page = Page(xml_file)
            # Find image (same name or image filename from page-xml file)
            imageFilename = page.imageFilename() if not same_names else xml_file.with_suffix(image_extension).name
            imageDir = xml_file
            for _ in range(0, len(image_folder.split('../'))):
                imageDir = imageDir.parent
            imageDir = imageDir.joinpath('./' + image_folder.rsplit('./')[0])
            imagePath = find_image(imageFilename, imageDir)
            if not imagePath:
                print(f"Warning: Image {imageFilename} not found in {imageDir}")
                continue
            image, image_format = get_image(imagePath)
            text_dict = {}
            # Find Textlines
            for textregion in page.regions.textregions:
                tr_id = textregion.get_id()
                text_dict[tr_id] = {}
                for line in textregion.textlines:
                    text = line.get_text()
                    line_id = line.get_id()
                    text_dict[tr_id][line_id] = text if text else ''

                    # Cut image
                    image_snippet = crop_image_by_polygon(image,
                                                          line.get_coordinates(returntype='mrr'),
                                                          save_snippet=save_snippets,
                                                          snippet_dir=imageDir.joinpath(imageFilename.rsplit('.', 1)[0]),
                                                          snippet_name=line_id)
                    # Convert image to Base64
                    image_snippet_b64 = image_to_base64(image_snippet)

                    # Process multiple requests
                    try:
                        response = completion(
                            model=llm_api.model_with_prefix,
                            api_base=llm_api.api_base_url,
                            api_key=llm_api.api_key,
                            timeout=llm_api.keep_alive_time,
                            stream=False,
                            temperature=0,
                            top_p=0,
                            n=1,  # Generate 1 response
                            messages=[
                                {
                                    "role": "user",
                                    "content": [
                                        {"type": "text", "text": prompt},
                                        {
                                            "type": "image_url",
                                            "image_url": {
                                                "url": f"data:image/{image_format.lower()};base64,{image_snippet_b64}",
                                                "detail": "high"  # Adjust to "high" for detailed analysis
                                            }
                                        }
                                    ]
                                }
                            ],
                            max_tokens=150,
                        )
                        print(f'{line_id} -> [green]{response.choices[0].message.content}[green]')
                        line.update_text(response.choices[0].message.content)
                    except Exception as e:
                        print("An error occurred during completion:", e)
                        continue

            if not dry_run:
                fout = xml_file.parent.joinpath(llm_api.model.replace('.','_').replace(':','-')).joinpath(xml_file.name)
                fout.parent.mkdir(parents=True, exist_ok=True)
                logging.info(f'Wrote modified xml file to output directory: {fout}')
                page.save_xml(fout)

if __name__ == "__main__":
    app()
