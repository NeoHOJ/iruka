import logging
from colors import strip_color


class ColoredFormatter(logging.Formatter):
    color_map = {
        logging.CRITICAL: '\x1b[1;7;91m',
        logging.ERROR:    '\x1b[1;31m',
        logging.WARNING:  '\x1b[1;33m',
        logging.INFO:     '\x1b[1;34m',
        logging.DEBUG:    '\x1b[2m',  # dimmed
    }
    ctrl_reset = '\x1b[0m'

    def format(self, record):
        color_str = self.color_map.get(record.levelno, None)
        has_color = color_str is not None
        color_str_res = self.ctrl_reset

        record.color_apply = color_str if has_color else ''
        record.color_reset = color_str_res if has_color else ''
        return super().format(record)


class ColorlessFormatter(logging.Formatter):
    def format(self, record):
        rec = super().format(record)
        return strip_color(rec)
