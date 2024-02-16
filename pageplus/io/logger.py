import logging
from datetime import datetime
from pathlib import Path

log_path = Path(__file__).parents[2].joinpath(datetime.now().strftime('logs/PagePlus_%H_%M_%d_%m_%Y.log'))
logging.basicConfig(level=logging.DEBUG, handlers=[logging.FileHandler(log_path, mode='w'),
                                                   logging.StreamHandler()])
