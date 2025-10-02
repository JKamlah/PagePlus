import re


def next_ocrmatch(subs, ocr):
    """
    Iterates through all findings from sub string in the ocrd text
    :param subs: sub string
    :param ocr: ocr string
    :return:
    """
    for sub in subs:
        for ocrmatch in re.finditer(sub, ocr):
            yield ocrmatch
