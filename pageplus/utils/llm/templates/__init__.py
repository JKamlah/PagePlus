"""PAGE-XML-aware prompt templates and postprocessors.

Layout is inspired by Churro's templates package: each task mode has a Jinja template
file under :mod:`pageplus.utils.llm.templates` and a registered postprocessor
in :mod:`pageplus.utils.llm.templates.postprocess`. Profiles (defined in
:mod:`pageplus.utils.llm.templates.profiles`) glue together (provider, model,
task_mode) -> (template, schema, postprocessor).

Public surface:
    * :class:`TemplateRegistry` -- stores Jinja templates and schemas.
    * :func:`render_prompt` -- renders the prompt for a given (mode, profile, ctx).
    * :func:`get_profile`   -- resolves a profile for (provider, model, task_mode).
    * :func:`postprocess`   -- dispatches to the registered postprocessor.
"""
from __future__ import annotations

from pageplus.utils.llm.templates.postprocess import (
    register_postprocessor,
    get_postprocessor,
    list_postprocessors,
)
from pageplus.utils.llm.templates.profiles import (
    register_profile,
    get_profile,
    resolve_profile,
    supported_task_modes,
)
from pageplus.utils.llm.templates.registry import (
    TemplateRegistry,
    render_prompt,
    render_page_xml_payload,
)

__all__ = [
    "TemplateRegistry",
    "render_prompt",
    "render_page_xml_payload",
    "register_postprocessor",
    "get_postprocessor",
    "list_postprocessors",
    "register_profile",
    "get_profile",
    "resolve_profile",
    "supported_task_modes",
]
