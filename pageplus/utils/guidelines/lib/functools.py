from collections import defaultdict, OrderedDict


def get_defaultdict(resultslvl: dict, newlvl: str, instance=OrderedDict):
    """
    Creates a new dictionary instance into another
    :param resultslvl: instance of the current level
    :param newlvl: name of the new  level
    :param instance: type of the defaultdict instance
    :return:
    """
    resultslvl[newlvl] = defaultdict(instance) if not resultslvl.get(newlvl, None) else resultslvl[newlvl]
