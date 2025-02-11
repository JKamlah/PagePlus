import cProfile
import pstats
import io
from functools import wraps
from pathlib import Path
from datetime import datetime
from collections import defaultdict
import json
import getpass

from rich import print

class ProfileFnRet:
    def __init__(self, params: bool = True, results: bool = True):
        self.name : str|None = None
        self.dir:  str|Path|None = None
        self.params: dict = {}
        self.results: list = []


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
                ret = getattr(wrapper, "profile", Profile())
                profilelog = {
                    "stats": {
                        "stime": datetime.now().ctime(),
                        "user": getpass.getuser(),
                        "duration": round(ps.total_tt, 2),
                    },
                }
                if ret.params:
                    profilelog["params"] = ret.params
                if  len(ret.results) > 0:
                    profilelog["results"] = ret.results
                ret.dir.mkdir(parents=True, exist_ok=True)

                # Load existing data
                fpath = ret.dir / "PagePlusProfile.json"
                if fpath.exists():
                    data = json.loads(fpath.read_text())
                else:
                    data = defaultdict(dict)
                data.setdefault(funcname, {})[ret.name] = profilelog
                fpath.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
                print(f"Wrote profile logs to: {Path(fpath)}")
            else:
                result = func(*args, **kwargs)
            return result
        return wrapper
    return decorator