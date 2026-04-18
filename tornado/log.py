#
# Copyright 2012 Facebook
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.
"""Logging support for Tornado.

Tornado uses three logger streams:

* ``tornado.access``: Per-request logging for Tornado's HTTP servers (and
  potentially other servers in the future)
* ``tornado.application``: Logging of errors from application code (i.e.
  uncaught exceptions from callbacks)
* ``tornado.general``: General-purpose logging, including any errors
  or warnings from Tornado itself.

These streams may be configured independently using the standard library's
`logging` module.  For example, you may wish to send ``tornado.access`` logs
to a separate file for analysis.
"""

import logging
import logging.handlers
import sys

from tornado.escape import _unicode
from tornado.util import basestring_type, unicode_type

try:
    import colorama  # type: ignore
except ImportError:
    colorama = None

try:
    import curses
except ImportError:
    curses = None  # type: ignore

from typing import Any, cast

# Logger objects for internal tornado use
access_log = logging.getLogger("tornado.access")
app_log = logging.getLogger("tornado.application")
gen_log = logging.getLogger("tornado.general")


def _stderr_supports_color() -> bool:
    try:
        if hasattr(sys.stderr, "isatty") and sys.stderr.isatty():
            if curses:
                curses.setupterm()
                if curses.tigetnum("colors") > 0:
                    return True
            elif colorama:
                if sys.stderr is getattr(
                    colorama.initialise, "wrapped_stderr", object()
                ):
                    return True
    except Exception:
        # Very broad exception handling because it's always better to
        # fall back to non-colored logs than to break at startup.
        pass
    return False


def _safe_unicode(s: Any) -> str:
    pass


class LogFormatter(logging.Formatter):
    """Log formatter used in Tornado.

    Key features of this formatter are:

    * Color support when logging to a terminal that supports it.
    * Timestamps on every log line.
    * Robust against str/bytes encoding problems.

    This formatter is enabled automatically by
    `tornado.options.parse_command_line` or `tornado.options.parse_config_file`
    (unless ``--logging=none`` is used).

    Color support on Windows versions that do not support ANSI color codes is
    enabled by use of the colorama__ library. Applications that wish to use
    this must first initialize colorama with a call to ``colorama.init``.
    See the colorama documentation for details.

    __ https://pypi.python.org/pypi/colorama

    .. versionchanged:: 4.5
       Added support for ``colorama``. Changed the constructor
       signature to be compatible with `logging.config.dictConfig`.
    """

    DEFAULT_FORMAT = "%(color)s[%(levelname)1.1s %(asctime)s %(module)s:%(lineno)d]%(end_color)s %(message)s"  # noqa: E501
    DEFAULT_DATE_FORMAT = "%y%m%d %H:%M:%S"
    DEFAULT_COLORS = {
        logging.DEBUG: 4,  # Blue
        logging.INFO: 2,  # Green
        logging.WARNING: 3,  # Yellow
        logging.ERROR: 1,  # Red
        logging.CRITICAL: 5,  # Magenta
    }

    def __init__(
        self,
        fmt: str = DEFAULT_FORMAT,
        datefmt: str = DEFAULT_DATE_FORMAT,
        style: str = "%",
        color: bool = True,
        colors: dict[int, int] = DEFAULT_COLORS,
    ) -> None:
        r"""
        :arg bool color: Enables color support.
        :arg str fmt: Log message format.
          It will be applied to the attributes dict of log records. The
          text between ``%(color)s`` and ``%(end_color)s`` will be colored
          depending on the level if color support is on.
        :arg dict colors: color mappings from logging level to terminal color
          code
        :arg str datefmt: Datetime format.
          Used for formatting ``(asctime)`` placeholder in ``prefix_fmt``.

        .. versionchanged:: 3.2

           Added ``fmt`` and ``datefmt`` arguments.
        """
        logging.Formatter.__init__(self, datefmt=datefmt)
        self._fmt = fmt

        self._colors: dict[int, str] = {}
        if color and _stderr_supports_color():
            if curses is not None:
                fg_color = curses.tigetstr("setaf") or curses.tigetstr("setf") or b""

                for levelno, code in colors.items():
                    # Convert the terminal control characters from
                    # bytes to unicode strings for easier use with the
                    # logging module.
                    self._colors[levelno] = unicode_type(
                        curses.tparm(fg_color, code), "ascii"
                    )
                normal = curses.tigetstr("sgr0")
                if normal is not None:
                    self._normal = unicode_type(normal, "ascii")
                else:
                    self._normal = ""
            else:
                # If curses is not present (currently we'll only get here for
                # colorama on windows), assume hard-coded ANSI color codes.
                for levelno, code in colors.items():
                    self._colors[levelno] = "\033[2;3%dm" % code
                self._normal = "\033[0m"
        else:
            self._normal = ""

    def format(self, record: Any) -> str:
        pass


def enable_pretty_logging(
    options: Any = None, logger: logging.Logger | None = None
) -> None:
    """Turns on formatted logging output as configured.

    This is called automatically by `tornado.options.parse_command_line`
    and `tornado.options.parse_config_file`.
    """
    if options is None:
        import tornado.options

        options = tornado.options.options
    if options.logging is None or options.logging.lower() == "none":
        return
    if logger is None:
        logger = logging.getLogger()
    logger.setLevel(getattr(logging, options.logging.upper()))
    if options.log_file_prefix:
        rotate_mode = options.log_rotate_mode
        if rotate_mode == "size":
            channel: logging.Handler = logging.handlers.RotatingFileHandler(
                filename=options.log_file_prefix,
                maxBytes=options.log_file_max_size,
                backupCount=options.log_file_num_backups,
                encoding="utf-8",
            )
        elif rotate_mode == "time":
            channel = logging.handlers.TimedRotatingFileHandler(
                filename=options.log_file_prefix,
                when=options.log_rotate_when,
                interval=options.log_rotate_interval,
                backupCount=options.log_file_num_backups,
                encoding="utf-8",
            )
        else:
            error_message = (
                "The value of log_rotate_mode option should be "
                + '"size" or "time", not "%s".' % rotate_mode
            )
            raise ValueError(error_message)
        channel.setFormatter(LogFormatter(color=False))
        logger.addHandler(channel)

    if options.log_to_stderr or (options.log_to_stderr is None and not logger.handlers):
        # Set up color if we are in a tty and curses is installed
        channel = logging.StreamHandler()
        channel.setFormatter(LogFormatter())
        logger.addHandler(channel)


def define_logging_options(options: Any = None) -> None:
    """Add logging-related flags to ``options``.

    These options are present automatically on the default options instance;
    this method is only necessary if you have created your own `.OptionParser`.

    .. versionadded:: 4.2
        This function existed in prior versions but was broken and undocumented until 4.2.
    """
    if options is None:
        # late import to prevent cycle
        import tornado.options

        options = tornado.options.options
    options.define(
        "logging",
        default="info",
        help=(
            "Set the Python log level. If 'none', tornado won't touch the "
            "logging configuration."
        ),
        metavar="debug|info|warning|error|none",
    )
    options.define(
        "log_to_stderr",
        type=bool,
        default=None,
        help=(
            "Send log output to stderr (colorized if possible). "
            "By default use stderr if --log_file_prefix is not set and "
            "no other logging is configured."
        ),
    )
    options.define(
        "log_file_prefix",
        type=str,
        default=None,
        metavar="PATH",
        help=(
            "Path prefix for log files. "
            "Note that if you are running multiple tornado processes, "
            "log_file_prefix must be different for each of them (e.g. "
            "include the port number)"
        ),
    )
    options.define(
        "log_file_max_size",
        type=int,
        default=100 * 1000 * 1000,
        help="max size of log files before rollover",
    )
    options.define(
        "log_file_num_backups", type=int, default=10, help="number of log files to keep"
    )

    options.define(
        "log_rotate_when",
        type=str,
        default="midnight",
        help=(
            "specify the type of TimedRotatingFileHandler interval "
            "other options:('S', 'M', 'H', 'D', 'W0'-'W6')"
        ),
    )
    options.define(
        "log_rotate_interval",
        type=int,
        default=1,
        help="The interval value of timed rotating",
    )

    options.define(
        "log_rotate_mode",
        type=str,
        default="size",
        help="The mode of rotating files(time or size)",
    )

    options.add_parse_callback(lambda: enable_pretty_logging(options))
