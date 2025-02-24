import json
import re
import subprocess
import sys
from collections import Counter
from importlib import util
from pathlib import Path
from typing import List, Annotated

import typer
from dotenv import set_key, find_dotenv
from rich import print

from pageplus.io.logger import logging
from pageplus.models.page import Page
from pageplus.utils.constants import ProfileLevel
from pageplus.utils.fs import collect_xml_files, find_image
from pageplus.utils.fs import transform_inputs
from pageplus.utils.image import image_to_base64, get_image, crop_image_by_polygon
from pageplus.utils.profile import profile, ProfileFnRet

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


else:

    from pageplus.utils.constants import Environments, LLMProvider
    from pageplus.utils.workspace import Workspace
    from pageplus.utils.llm.api import LLMAPI

    from litellm import completion
    from pydantic import BaseModel

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
                     service: Annotated[str, typer.Argument(help="Service")] = "DEFAULT") -> None:
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
        force_linebreak = True

        def call_llm(input_data, fulltext):
            # Create the prompt text that instructs the model what to do
            system = """You are an expert in spellchecking.
            Analyse the input and find all possible OCR errors and misspelling.
            Preserve hyphenation as it appears. Do not merge words split by hyphens at the end of lines.
            Please write out our findings numbered in the following manner: 

            The original input is a json object:
            {'lines': [{'id': id, 'original': text},..]}

            You create add to this input a new entry "corrected" and output also an JSON Object:
            {'lines': [{'id': id, 'corrected': corrected_text},..]}

            Only output the JSON!"""
            # print(prompt)

            try:
                import html
                print(input_data)
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
                            "role": "system",
                            "content": [
                                {"type": "text", "text": system},
                            ]
                        },
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": html.escape(f"{input_data}")},
                            ]
                        }
                    ],
                    response_format={
                                      "type": "json_schema",
                                      "json_schema": {
                                        "name": "correction_response",
                                        "strict": True,
                                        "schema": {
                                          "type": "object",
                                          "properties": {
                                            "lines": {
                                              "type": "array",
                                              "items": {
                                                "type": "object",
                                                "properties": {
                                                  "id": { "type": "string" },
                                                  "corrected": { "type": "string" }
                                                },
                                                "required": ["id", "corrected"],
                                                "additionalProperties": False
                                              }
                                            }
                                          },
                                          "required": ["lines"],
                                          "additionalProperties": False
                                        }
                                      }
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

            # Convert lists to dicts for easier merging
            input_data = {item["id"]: item for item in input_data["lines"]}
            corrected_data = {item["id"]: item for item in json.loads(html.unescape(json_str))["lines"]}

            # Merge the dictionaries
            merged_dict = {
                "lines": [
                    {**corrected_data[key], **input_data[key]} for key in input_data.keys() & corrected_data.keys()
                ]
            }
            # Replace double oblique hyphens
            if force_linebreak:
                for idx, line in enumerate(merged_dict['lines']):
                    merged_dict['lines'][idx]['corrected'] = re.sub('⸗!$', '-', merged_dict['lines'][idx]['corrected'])
                    merged_dict['lines'][idx]['original'] = re.sub('⸗!$', '-', merged_dict['lines'][idx]['original'])

            return merged_dict

        xml_files = collect_xml_files(map(Path, inputs))
        # Raise error if no xml files are found
        if not xml_files:
            raise FileNotFoundError('No xml files found in input directory')
        for xml_file in xml_files:
            print(xml_file)
            page = Page(xml_file)
            fulltext = page.extract_fulltext()
            corrected_lines = {'lines': []}
            for textregion in page.regions.textregions:
                text_dict = {"lines": []}
                for line in textregion.textlines:
                    text = line.get_text()
                    text = re.sub('-$', '⸗!', text) if force_linebreak else text
                    text_dict['lines'].append({'id': line.get_id(), "original": text if text else ''})
                    if len(text_dict['lines']) > 10:
                        corrected_lines['lines'].append(call_llm(text_dict, fulltext))
                        text_dict = {"lines": []}
                if len(text_dict['lines']) > 0:
                    corrected_lines['lines'].append(call_llm(text_dict, fulltext))
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
            page.delete_textlevel('region')
            fulltext = page.extract_fulltext()
            # prompt = f"""Here is the fulltext to analyze:\n{fulltext}"""
            prompt = {'text': []}
            [prompt['text'].append({'original': line}) for line in fulltext.split('\n')]
            system = """You are an expert in spellchecking.
Analyse the input and find all possible OCR errors and misspelling.
Please write out our findings numbered in the following manner: 

The original input is a json object:
{'text': ['lineid': id, 'original': text]}

You create add to this input a new entry "corrected" and output also an JSON Object:
{'text': [{'corrected': corrected_text}]}

Only output the JSON!"""

            class Corrections(BaseModel):
                corrections: str
                original: str

            class CorrectionsList(BaseModel):
                lines: list[Corrections]

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
                            "role": "system",
                            "content": [
                                {"type": "text", "text": system},
                            ]
                        },
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": f"{prompt}"},
                            ]
                        }
                    ],
                    response_format={ "type": "json_object" },
                    max_tokens=8000,
                )
                answer = response.choices[0].message.content
                print(json.loads(answer))

                # Save corrected lines to XML
                with xml_file.with_suffix('.spellchecked.text').open('w', encoding='utf-8') as fout:
                    fout.write(answer)

            except Exception as e:
                print("An error occurred during completion:", e)

    def ocr_settings(ctx: typer.Context, param: typer.CallbackParam, value):
        model, api_key, api_url, provider = llm_api.model, llm_api.api_key, llm_api.api_base_url, llm_api.provider
        def copy_provider():
            set_provider(llm_api.llmprovider(), 'OCR')
            llm_api.api_base_url = api_url
            llm_api.api_key = api_key
            llm_api.model = model

        match param.name:
            case "provider" if (value and value != llm_api.provider):
                copy_provider()
            case "api_base_url" if (value and value != llm_api.api_base_url):
                if not llm_api.provider.endswith('OCR'):
                    copy_provider()
                llm_api.api_base_url = model
            case "model_name" if (value and value != llm_api.model):
                if not llm_api.provider.endswith('OCR'):
                    copy_provider()
                llm_api.model = value
            case _:
                pass
        return None


    @app.command()
    @profile('llm-ocr')
    def ocr(inputs: Annotated[List[str],
    typer.Argument(exists=True, help="Paths to the XML files to be checked.", callback=transform_inputs)] = None,
            image_folder: Annotated[str, typer.Argument(exists=True,
                                                        help="Folder to the images relative to page-xml (default same as input)")] = '.',
            provider: Annotated[
                str, typer.Option(help="Set the model on the fly, otherwise set via 'llm set-model'",
                                  callback=ocr_settings)] = None,
            api_base_url: Annotated[str, typer.Option(help="Set API Base URL'", callback=ocr_settings)] = None,
            model_name: Annotated[str, typer.Option(help="Set the model on the fly, otherwise set via 'llm set-model'",
                                                    callback=ocr_settings)] = None,
            same_names: Annotated[bool, typer.Option(
                help="Use the page-xml filename to search for the image (default use imageFilename from pagexml file)")] = False,
            image_extension: Annotated[str, typer.Option(
                help="Filename extension of the images (only active with 'same_names' option)")] = '.jpg',
            save_snippets: Annotated[bool, typer.Option(help="Save snippets (debug option)")] = False,
            text_filter: Annotated[str, typer.Option(
                help="A regular expression, if specific textlines should be filtered")] = None,
            region_tagfilter: Annotated[str, typer.Option(
                help="A regular expression, if specific textlines should be filtered")] = None,
            textline_tagfilter: Annotated[str, typer.Option(
                help="A regular expression, if specific textlines should be filtered")] = None,
            only_user_prompt: Annotated[bool, typer.Option(help="Deactivate system prompts (for older API)")] = False,
            json_object: Annotated[bool, typer.Option(help="Use json_object instead of json_schema.")] = False,
            profile: Annotated[str, typer.Option(help="Profile function with tag (default:'' no profiling active.")] = '',
            profilelevel: Annotated[List[ProfileLevel],
                typer.Option(
                    help="Level of profiling. Options: 'stats' (always true), 'params', 'results', 'analytics', 'summary'")
            ] = ("stats", "params", "analytics", "summary"),
            overwrite: Annotated[
                bool, typer.Option(help="If True, ignores outputdir and overwrites input data.")] = False,
            dry_run: Annotated[bool, typer.Option(help="If True, the function will not write any files.")] = False):
        """
        OCR with the existing layout information. Existing text will be overwritten.
        """
        # API details
        # Turn profiling on
        ocr.profile = ProfileFnRet()
        ocr.profile.name = profile
        ocr.profile.dir = Path(inputs[0]).absolute() if len(inputs) > 0 else ''
        ocr.profile.stats = {'pages': 0, 'lines': 0}
        if util.find_spec('pageplus.utils.dinglehopper.edit_distance') is None:
            profilelevel.remove(ProfileLevel.analytics)
            print("[red]Warning:[/red] 'analytics' profiling level requires 'dinglehopper' package to be installed. "
                  "It will be disabled.")
        elif 'analytics' in profilelevel:
            from pageplus.cli.dinglehopper import count_diff, get_metrics, summarize_metrics

        system = ("You are an expert in recognizing text in an image, without modifying the results.\n"
                  "It is not allowed to add additional characters.\n"
                  "Recognize the text in the images: word by word!  No explanation, no newlines, with punctuations.\n"
                  "The input:\n"
                  "Image\n"
                  "Do not provide alternative variation!\n"
                  "Output format JSON (a single line with the information)(only output one version via line, dont repeat!):\n"
                  "{'text': [First-line, Next-line,...]}")

        prompt = ("Please read the content of this image:")
        if 'params' in profilelevel:
            ocr.profile.params = {'model': llm_api.model_with_prefix,
                                  'api_base': llm_api.api_base_url,
                                  'prompts': {'system': system, 'user': prompt},
                                  'text-filter': text_filter,
                                  'region-tagfilter': region_tagfilter,
                                  'textline-tagfilter': textline_tagfilter}
        # Read XML
        xml_files = collect_xml_files(map(Path, inputs))
        # Raise error if no xml files are found
        if not xml_files:
            raise FileNotFoundError('No xml files found in input directory')
        reg_filter = re.compile(rf"{text_filter}") if text_filter is not None else '.'
        all_diff = Counter()
        all_metrics = []
        for xml_file in xml_files:
            print(xml_file)
            # Read XML content
            page = Page(xml_file)
            page.delete_textlevel('region')
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
            page_diff = Counter()
            page_metrics = []
            # Find Textlines
            for textregion in page.regions.textregions:
                tr_id = textregion.get_id()
                if region_tagfilter is not None and region_tagfilter != textregion.get_tag():
                    continue
                text_dict[tr_id] = {}
                for line in textregion.textlines:
                    if textline_tagfilter is not None and textline_tagfilter != line.get_tag():
                        continue
                    text = line.get_text()
                    if text_filter is not None and not re.search(reg_filter, text):
                        continue
                    line_id = line.get_id()
                    text_dict[tr_id][line_id] = {'original': text} if text else {'original': ''}

                    # Cut image
                    image_snippet, _ = crop_image_by_polygon(image,
                                                          line.get_coordinates(returntype='mrr'),
                                                          save_snippet=save_snippets,
                                                          square_canvas=True,
                                                          snippet_dir=imageDir.joinpath(imageFilename.rsplit('.', 1)[0]),
                                                          snippet_name='snippet_'+line_id)
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
                            temperature= 0.000001, # Can create problems if set to 0
                            top_p= 0.000001, # Can create problems if set to 0
                            n=1,  # Generate 1 response
                            messages=[
                                {
                                    "role": "user" if only_user_prompt else "system",
                                    "content": [
                                        {"type": "text", "text": system},
                                    ]
                                },
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
                            response_format= {"type": "json_object" if json_object else "json_schema",
                                              "json_schema": {
                                                "name": "ocrresponse",
                                                "strict": True,
                                                "schema": {
                                                  "type": "object",
                                                  "properties": {
                                                    "text": {
                                                      "type": "array",
                                                        "items": {
                                                          "type": "string"
                                                        },
                                                    }
                                                  },
                                                  "strict": True,
                                                  "required": ["text"],
                                                }
                                              }
                                            },
                            max_tokens=300,
                       )
                        try:
                            import json_repair
                            output = json_repair.repair_json(response.choices[0].message.content, return_objects=True)
                            ocr_text = ' '.join(output["text"]) if isinstance(output["text"], list) else output["text"]
                            print(f'{line_id} -> [green]{ocr_text}[green]')
                            line.update_text(ocr_text)
                            text_dict[tr_id][line_id]['ocr'] = ocr_text
                            if 'analytics' in profilelevel:
                                line_diff = count_diff(text, ocr_text)
                                page_diff.update(line_diff)
                                page_metrics.append(get_metrics(text, ocr_text, line_diff))
                        except:
                            print(f"{line_id} -> [red] Error: No valid output[red]")
                    except Exception as e:
                        print("An error occurred during completion:", e)
                        continue
            if 'results' in profilelevel:
                ocr.profile.results.append({xml_file.name :text_dict})
            ocr.profile.stats['pages'] += any([1 for region in text_dict.values() if len(region.values()) > 0])
            ocr.profile.stats['lines'] += sum([len(region.values()) for region in text_dict.values()])
            if 'analytics' in profilelevel:
                metrics = summarize_metrics(page_metrics) if len(page_metrics) > 0 else {}
                all_metrics.extend(page_metrics)
                ocr.profile.analytics.append({xml_file.name : {'metrics': metrics,
                                                               'confusions': dict(page_diff)}})
                all_diff.update(page_diff)
            if not dry_run:
                fout = xml_file if overwrite else xml_file.parent.joinpath(llm_api.model.replace('.','_').replace(':','-')).joinpath(xml_file.name)
                fout.parent.mkdir(parents=True, exist_ok=True)
                logging.info(f'Wrote modified xml file to output directory: {fout}')
                page.save_xml(fout)
        if 'summary' in profilelevel:
            if 'analytics' in profilelevel:
                metrics = summarize_metrics(all_metrics)
                ocr.profile.summary['analytics'] = {'metrics': metrics,
                                             'confusions': dict(all_diff)}

if __name__ == "__main__":
    app()
