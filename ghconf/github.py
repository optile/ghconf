# -* encoding: utf-8 *-
import importlib
import inspect
import socket
import time
import re
from datetime import datetime, timezone
from types import ModuleType
from typing import Callable, Any,  cast, Dict

import github
import urllib3

from github.GithubException import GithubException
from github.GithubObject import GithubObject
from github.PaginatedList import PaginatedList
from github import Github
from requests import ConnectionError as RequestsConnectionError  # don't shadow builtin ConnectionError
from wrapt import synchronized

from ghconf.utils import print_debug, print_info, print_error, ErrorMessage, ttywrite, highlight, resumebar, suspendbar
import aspectlib


gh = cast(Github, None)  # type: Github


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


@aspectlib.Aspect(bind=True)
def retry_on_server_failure(cutpoint: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    # yes, I know about aspectlib.contrib.retry(), but this one logs
    e = None  # type: GithubException
    for i in range(4):
        if i < 3:
            try:
                yield aspectlib.Proceed
                if i > 0:
                    print_info("Retry successful. Moving on...")
                break
            except GithubException as e:
                if e.status >= 500:
                    print_info("Received a server error %s from GitHub. Retry %s/3" % (str(e.status), str(i + 1)))
                    time.sleep(1)
                    continue
                elif e.status == 404:
                    raise
                else:
                    print_error("Received server error %s from GitHub. Won't retry." % str(e.status))
                    raise
            except socket.timeout as e:
                print_error("Received socket timeout (%s). Retry %s/3" % (str(e), str(i + 1)))
                continue
            except (ConnectionError, RequestsConnectionError, urllib3.exceptions.HTTPError) as e:
                print_error("Received connection error (%s). Retry %s/3" % (str(e), str(i + 1)))
                continue
        else:
            raise ErrorMessage("3 retries didn't yield results. Exiting.")


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
                    [handle_rate_limits, retry_on_server_failure],
                    methods=re.compile(r'(?!__getattribute__$|rate_limiting$|get_rate_limit$|'
                                       r'rate_limiting_resettime$|(_|_.*?_)make[a-zA-Z]+Attribute$|'
                                       r'_useAttributes$|_initAttributes$|__init__$)'))
    if dry_run:
        aspectlib.weave([github.GithubObject.GithubObject, github.PaginatedList.PaginatedList],
                        enforce_dryrun, methods=re.compile(r"(^edit|^remove|^create|^replace)"))


@synchronized
def get_github(github_token: str = "", dry_run: bool = False, *args: Any, **kwargs: Any) -> Github:
    global gh

    weave_magic(dry_run)

    if not gh:
        if not github_token:
            raise TypeError("Can't initialize Github instance without github_token")
        print_debug("Initializing Github instance")
        gh = Github(github_token, *args, **kwargs)

    return gh
