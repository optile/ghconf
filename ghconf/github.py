# -* encoding: utf-8 *-
import importlib
import inspect
import time
import re
from datetime import datetime, timezone
from types import ModuleType
from typing import Callable, Any,  cast, Dict

import github

from github.GithubException import GithubException
from github.GithubObject import GithubObject
from github.PaginatedList import PaginatedList
from github import Github
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
    yield  # type: ignore


def weave_magic(cls: type, dry_run: bool = False) -> None:
    if issubclass(cls, (github.GithubObject.GithubObject, github.PaginatedList.PaginatedList)):
        aspectlib.weave(cls, [handle_rate_limits, retry_on_server_failure],
                        methods=re.compile('(?!__getattribute__$|rate_limiting$|get_rate_limit$|'
                                           'rate_limiting_resettime$)'))
        if dry_run:
            aspectlib.weave(cls, enforce_dryrun, methods=re.compile(r"(^edit|^remove|^create|^replace)"))


def patch_tree(root_module: ModuleType, patcher: Callable[[type, bool], None], dry_run: bool = False,
               path: str = "") -> None:
    for symbol in dir(root_module):
        try:
            sympath = "%s%s" % ("%s." % path, symbol)
            mod = importlib.import_module(sympath, root_module.__name__)
        except ModuleNotFoundError:
            pass
        else:
            new_path = "%s%s" % ("%s." % path if path else "", mod.__name__)
            patch_tree(mod, patcher, dry_run, new_path)
            continue

        cls = getattr(root_module, symbol)
        if inspect.isclass(cls):
            patcher(cls, dry_run)


@synchronized
def get_github(github_token: str = None, dry_run: bool = False, *args: Any, **kwargs: Any) -> Github:
    global gh

    patch_tree(github, weave_magic, dry_run)

    if not gh:
        if not github_token:
            raise TypeError("Can't initialize Github instance without github_token")
        print_debug("Initializing Github instance")
        gh = Github(github_token, *args, **kwargs)

    return gh
