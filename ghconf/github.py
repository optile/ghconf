# -* encoding: utf-8 *-
import socket
import threading
import time
import re
from datetime import datetime, timezone
from types import TracebackType
from typing import Callable, Any, cast, Dict, TypeVar, Type
from typing import Optional

import github
import github.Requester
import github.PaginatedList
import github.GithubObject
import urllib3

from github.GithubException import GithubException
from requests import ConnectionError as RequestsConnectionError  # don't shadow builtin ConnectionError
from wrapt import synchronized

from ghconf.utils import print_debug, print_info, print_error, ErrorMessage, ttywrite, highlight, resumebar, suspendbar
import aspectlib


gh = cast(github.Github, None)  # type: github.Github


def default_waitticker(second: int, wait: int) -> None:
    remain = wait - second
    if second == 1:
        suspendbar()
    ttywrite("Waiting for %s seconds          " % highlight(str(remain)), end="\r" if remain > 0 else "\n")
    if remain <= 0:
        resumebar()


# This is a poor man's notification method that code can use to provide user
# feedback when the github module gets rate limited. For an example, see
# the progress bar in main.py
waittickers = {}  # type: Dict[str, Callable[[int, int], None]]


def waittick(second: int, wait: int) -> None:
    if len(waittickers) == 0:
        default_waitticker(second, wait)
    else:
        for _, ticker in waittickers.items():
            ticker(second, wait)


# ----
# Aspect-oriented programming in Python??! I finally found a use for it! :). This module proxies PyGithub to
# manage rate-limiting across all GitHub APIs.
# ----


def check_rate_limits() -> None:
    # check the rate limits
    remaining, limit = gh.rate_limiting
    time_to_wait = gh.rate_limiting_resettime - int(datetime.now(timezone.utc).timestamp())

    # only a few calls left, so let's sleep for a bit
    if remaining < 20 and time_to_wait > 0:
        print_info("rate limited. sleeping for %s seconds" % time_to_wait)
        for i in range(0, time_to_wait):
            time.sleep(1)
            waittick(i + 1, time_to_wait)


@aspectlib.Aspect(bind=True)
def handle_rate_limits(cutpoint: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    check_rate_limits()
    # then, execute the function we're proxying
    yield aspectlib.Proceed


class StackDepthWatcher:
    def __init__(self) -> None:
        self.store = threading.local()
        self.store.depth = 0

    def __enter__(self) -> int:
        cur = self.store.depth
        self.store.depth += 1

        # grab some stats on how deep the nested stack of aspects gets
        if threading.get_ident() in StackDepthWatcher.maxdepth:
            if self.store.depth > StackDepthWatcher.maxdepth[threading.get_ident()]:
                StackDepthWatcher.maxdepth[threading.get_ident()] = self.store.depth
        else:
            StackDepthWatcher.maxdepth[threading.get_ident()] = self.store.depth
        return cur

    def __exit__(self, exc_type: Type[BaseException], exc_val: Optional[BaseException],
                 exc_tb: TracebackType) -> bool:
        cur = self.store.depth
        self.store.depth -= 1

        # grab some stats to understand how often we reach the bottom of the stack
        if self.store.depth == 0 and cur > self.store.depth:
            if threading.get_ident() in StackDepthWatcher.tozero:
                StackDepthWatcher.tozero[threading.get_ident()] += 1
            else:
                StackDepthWatcher.tozero[threading.get_ident()] = 1
        return False


StackDepthWatcher.maxdepth = {}
StackDepthWatcher.tozero = {}
stackdepth = StackDepthWatcher()


@aspectlib.Aspect(bind=True)
def retry_on_server_failure(cutpoint: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    # yes, I know about aspectlib.contrib.retry(), but this one logs
    exc = None  # type: Optional[Exception]

    with stackdepth as depth:
        if depth == 0:
            for i in range(3):
                try:
                    yield aspectlib.Proceed
                    if i > 0:
                        print_debug("Retry %s successful" % (i + 1))
                    break
                except GithubException as e:
                    if e.status >= 500:
                        print_debug("Received a server error %s from GitHub. Retry %s/3\nData: %s" %
                                    (str(e.status), str(i + 1), e.args))
                        time.sleep(1)
                        exc = e
                        continue
                    elif e.status == 404:
                        raise
                    else:
                        print_error("Received server error %s from GitHub. Won't retry." % str(e.status))
                        raise
                except socket.timeout as e:
                    print_error("Received socket timeout (%s). Retry %s/3" % (str(e), str(i + 1)))
                    exc = e
                    continue
                except (ConnectionError, RequestsConnectionError, urllib3.exceptions.HTTPError) as e:
                    print_error("Received connection error (%s). Retry %s/3" % (str(e), str(i + 1)))
                    exc = e
                    continue
            else:
                if isinstance(exc, GithubException):
                    print_error("3 retries didn't yield results.")
                    raise exc
                else:
                    raise ErrorMessage("3 retries didn't yield results.")
        else:
            yield aspectlib.Proceed


class DryRunException(Exception):
    pass


@aspectlib.Aspect(bind=True)
def enforce_dryrun(cutpoint: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    raise DryRunException("While in dryrun mode, a module tried to call '%s'. Inspect the stack trace to find out "
                          "who. If the call is ok, add an exception to ghconf.github.enforce_dryrun" %
                          cutpoint.__name__)
    # enforce_dryrun must be a generator... so this is an unreachable yield
    yield


def weave_magic(dry_run: bool = False) -> None:
    aspectlib.weave([github.GithubObject.GithubObject, github.PaginatedList.PaginatedList],
                    [retry_on_server_failure, handle_rate_limits],
                    methods=re.compile(r'(?!__getattribute__$|rate_limiting$|get_rate_limit$|'
                                       r'rate_limiting_resettime$|(_|_.*?_)make[a-zA-Z]+Attribute$|'
                                       r'_useAttributes$|_initAttributes$|__init__$)'))
    if dry_run:
        aspectlib.weave([github.GithubObject.GithubObject, github.PaginatedList.PaginatedList],
                        enforce_dryrun, methods=re.compile(r"(^edit|^remove|^create|^replace)"))


@synchronized
def get_github(github_token: str = "", dry_run: bool = False, *args: Any, **kwargs: Any) -> github.Github:
    global gh

    weave_magic(dry_run)

    if not gh:
        if not github_token:
            raise TypeError("Can't initialize Github instance without github_token")
        print_debug("Initializing Github instance")
        gh = github.Github(github_token, *args, **kwargs)

    return gh
