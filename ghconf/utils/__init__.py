# -* encoding: utf-8 *-
import time
import queue
import shutil
import threading
from dataclasses import dataclass, field
from textwrap import TextWrapper
from typing import List, Any, Optional, Callable, Tuple, Dict
from typing import Type

import colorama
from tqdm import tqdm
from colorama import Fore, Style

from ghconf.utils.ansi import ANSITextWrapper, strip_ANSI

enable_debug_output = False  # type: bool
enable_verbose_output = False  # type: bool
enable_color = True  # type: bool
enable_progressbar = True  # type: bool

success_color = Fore.GREEN  # type: str
debug_hl = Fore.LIGHTMAGENTA_EX  # type: str
debug_color = Fore.MAGENTA  # type: str
info_hl = Fore.LIGHTCYAN_EX  # type: str
info_color = Fore.LIGHTBLUE_EX  # type: str
warning_hl = Fore.LIGHTWHITE_EX  # type: str
warning_color = Fore.YELLOW  # type: str
error_hl = Fore.LIGHTRED_EX  # type: str
error_color = Fore.RED  # type: str
highlight_color = Fore.LIGHTWHITE_EX  # type: str
color_reset = Style.RESET_ALL  # type: str

_TextWrapper = ANSITextWrapper  # type: Type[TextWrapper]


def init_color(no_color: bool) -> None:
    global success_color, info_hl, info_color, warning_hl, warning_color, error_hl, error_color, highlight_color, \
        color_reset, _TextWrapper

    if no_color:
        success_color = info_hl = info_color = warning_hl = warning_color = error_hl = error_color = highlight_color = \
            color_reset = ""
        _TextWrapper = TextWrapper
    else:
        colorama.init()


_pbar = None  # type: Optional[tqdm]
_queue = queue.Queue()
_prompt_response = queue.Queue(maxsize=1)


@dataclass
class TtyMessage:
    msg: str
    kwargs: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PromptMessage:
    msg: str
    choices: List[str] = field(default_factory=list)
    default: Optional[str] = None
    ignore_case: bool = True


def progressbar(total: Optional[int] = None) -> tqdm:
    """
    wrapper around tqdm that allows print_wrapped to work with one(!)
    active progressbar.
    :param total: total number of iterations
    :return: a tqdm instance
    """
    global _pbar
    if not _pbar:
        _pbar = tqdm(
            bar_format="  {{n:>{len}}}/{{total}}  |{{bar}}| {{percentage:3.0f}}%  "
                       "{{remaining}}   ".format(len=len(str(total))),
            ascii=True, total=total, leave=False
        )
        _pbar.ghconf_close = _pbar.close

        # this is so hacky.. it'll do at most for this command-line tool.
        def override_close(_self) -> None:
            global _pbar
            if _pbar:
                _pbar.ghconf_close()
                _pbar = None

        _pbar.close = override_close.__get__(_pbar, tqdm)
    return _pbar


def suspendbar() -> None:
    if _pbar:
        print_debug("Suspending progress bar...")
        _pbar.clear()


def resumebar() -> None:
    if _pbar:
        print_debug("Resuming progress bar...")
        _pbar.refresh()


def _ttywrite(msg: str = "", **kwargs: Any) -> None:
    """
    This should only be called on the output thread.
    :param msg:
    :param kwargs:
    """
    if _pbar:
        _pbar.write(msg, **kwargs)
    else:
        print(msg, **kwargs)


def ttywrite(msg: str = "", **kwargs: Any) -> None:
    """
    Use this instead of ``print()`` whenever possible so that your code cooperates with progressbars correctly.
    :param msg:
    :param kwargs:
    """
    _queue.put(TtyMessage(
        msg, kwargs
    ))


def ttywriter(alivefunc: Callable[[], bool]) -> None:
    while alivefunc() or not _queue.empty():
        item = _queue.get(True)
        if isinstance(item, TtyMessage):
            _ttywrite(item.msg, **item.kwargs)
        elif item is StopIteration or isinstance(item, StopIteration):
            break
        elif isinstance(item, PromptMessage):
            resp = _prompt(item.msg, item.choices, item.default, item.ignore_case)
            _prompt_response.put(resp)


def _prompt(promptstr: str, choices: Optional[List[str]] = None, default: Optional[str] = None,
            ignore_case: bool = True) -> str:
    suspendbar()
    while True:
        try:
            resp = input(promptstr)
        except EOFError as e:
            raise ErrorMessage("Input cancelled. Break. (%s)" % str(e))

        if ignore_case:
            resp = resp.lower()
        if (choices and resp in choices) or choices is None:
            break
        elif resp == "" and default:
            resp = default
            break

    resumebar()
    return resp


def prompt(promptstr: str, choices: Optional[List[str]] = None, default: Optional[str] = None,
           ignore_case: bool = True) -> str:
    _queue.put(PromptMessage(
        promptstr, choices, default, ignore_case
    ))
    return _prompt_response.get(True)


def print_wrapped(msg: str, msgtype: str = "", **kwargs: Any) -> None:
    cols = kwargs.pop("cols", shutil.get_terminal_size()[0])
    cols = cols - kwargs.pop("redge", 0)
    indent = kwargs.pop("indent", (len(strip_ANSI(msgtype))) * " ")
    tw = _TextWrapper(
        width=cols,
        subsequent_indent=indent,
    )
    if msgtype:
        ttywrite(tw.fill("{type}{msg}".format(type=msgtype, msg=msg)), **kwargs)
    else:
        ttywrite(tw.fill(msg), **kwargs)


def print_error(message: str, **kwargs: Any) -> None:
    err = "%s%s%s%s%s" % (error_hl, "***", error_color, " ERROR: ", color_reset)
    print_wrapped(message, err, **kwargs)


def print_warning(message: str, **kwargs: Any) -> None:
    warn = "%s%s%s%s%s" % (warning_hl, "***", warning_color, " WARNING: ", color_reset)
    print_wrapped(message, warn, **kwargs)


def print_info(message: str, **kwargs: Any) -> None:
    info = "%s%s%s%s%s" % (info_hl, "*", info_color, " Info: ", color_reset)
    print_wrapped(message, info, **kwargs)


def print_debug(message: str, **kwargs: Any) -> None:
    if enable_debug_output:
        debug = "%s%s%s%s%s" % (debug_hl, "*", debug_color, " Debug: ", color_reset)
        print_wrapped(message, debug, **kwargs)


def success(message: str) -> None:
    print_wrapped("%s%s%s" % (success_color, message, color_reset))


def error(message: str) -> None:
    print_wrapped("%s%s%s" % (error_color, message, color_reset))


def highlight(message: str) -> str:
    return "%s%s%s" % (highlight_color, message, color_reset)


class ErrorMessage(Exception):
    def __init__(self, ansi_msg: str, exitcode: int = 1) -> None:
        super().__init__(ansi_msg)
        self.ansi_msg = ansi_msg
        self.exitcode = exitcode

    def __str__(self) -> str:
        return self.ansi_msg
