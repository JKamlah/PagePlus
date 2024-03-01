import logging
from datetime import datetime
from pathlib import Path

log_path = Path(__file__).parents[2].joinpath(datetime.now().strftime('logs/PagePlus_%Y-%m-%d.log'))
logging.basicConfig(level=logging.DEBUG, handlers=[logging.FileHandler(log_path, mode='a+'),
                                                   logging.StreamHandler()])
