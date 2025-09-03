import cProfile
import getpass
import io
import json
import pstats
import re
from collections import defaultdict
from datetime import datetime
from functools import wraps
from pathlib import Path

from rich import print


class ProfileFnRet:
    def __init__(self, params: bool = True, results: bool = True):
        self.name: str | None = None
        self.dir: str | Path | None = None
        self.stats: dict = {}
        self.params: dict = {}
        self.results: list = []
        self.analytics: list = []
        self.summary: dict = {}


def profile(funcname: str):
    """Decorator to profile a function and save results to a file."""

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            if 'profile' in kwargs and kwargs.get('profile') != '':
                profiler = cProfile.Profile()
                profiler.enable()
                result = func(*args, **kwargs)  # Execute function
                profiler.disable()
                # Capture profiling statisticsKe
                s = io.StringIO()
                ps = pstats.Stats(profiler, stream=s).sort_stats("cumulative")
                ret = getattr(wrapper, "profile", ProfileFnRet())
                profilelog = {
                    "stats": {
                        "start-time": datetime.now().ctime(),
                        "user": getpass.getuser(),
                        "time-dimension": 'seconds',
                        "total-time": round(ps.total_tt, 2),
                    },
                }
                profilelog["stats"].update(ret.stats)
                if re.search('ocr', funcname):
                    profilelog["stats"]["time-per-page"] = round(
                        ps.total_tt / ret.stats['pages'], 2)
                    profilelog["stats"]["time-per-line"] = round(
                        ps.total_tt / ret.stats['lines'], 2)
                if ret.params:
                    profilelog["params"] = ret.params
                if len(ret.results) > 0:
                    profilelog["results"] = ret.results
                if len(ret.analytics) > 0:
                    profilelog["analytics"] = ret.analytics
                profilelog["summary"] = ret.summary
                if ret.dir.is_file():
                    ret.dir.parent.mkdir(parents=True, exist_ok=True)
                    fpath = ret.dir.parent.joinpath("PagePlusProfile.json")
                else:
                    ret.dir.mkdir(parents=True, exist_ok=True)
                    fpath = ret.dir.joinpath("PagePlusProfile.json")
                if fpath.exists():
                    data = json.loads(fpath.read_text())
                else:
                    data = defaultdict(dict)
                data.setdefault(funcname, {})[ret.name] = profilelog
                fpath.write_text(
                    json.dumps(
                        data,
                        indent=2,
                        ensure_ascii=False),
                    encoding="utf-8")
                print(f"Wrote profile logs to: {fpath}")
            else:
                result = func(*args, **kwargs)
            return result
        return wrapper
    return decorator
