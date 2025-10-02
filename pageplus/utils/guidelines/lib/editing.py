from collections import defaultdict
from functools import lru_cache


def subcounter(func):
    """
    Wrapper helper count function
    :param func: function
    :return:
    """

    def helper(*_args, **_kwargs):
        helper.calls[_args[0] + "→" + _args[1]] += 1
        return func(*_args, **_kwargs)

    helper.calls = defaultdict(int)
    return helper


@subcounter
@lru_cache()
def substitutiontext(gtmatch: str, ocrmatch: str):
    """
    Create a string that highlights subsituted parts
    :param gtmatch: original string
    :param ocrmatch: new ocr'd string
    :return:
    """
    return f"--{gtmatch}--++{ocrmatch}++"


def string_index_replacement(text: str, idx: int, rep: str, idxrange: int = 1):
    textlist = list(text)
    textlist[idx:idx + idxrange] = rep
    text = "".join(textlist)
    return text


def update_replacement(guideline: dict, gt: str, ocr, ocridx: int):
    """
    Updates the ocr'd string
    :param guideline: guideline which character should be replaced
    :param gt: original string
    :param ocr: new ocr'd string
    :param ocridx: index of the substitution characters
    :return:
    """
    rep = guideline.get("<--").get(gt, None) if guideline.get('<--', None) else None
    if rep:
        if isinstance(ocr, str):
            ocr = string_index_replacement(ocr, ocridx, rep)
        else:
            ocr[ocridx] = rep
    return ocr
