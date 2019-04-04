# -* encoding: utf-8 *-
import functools
import time
import re
from datetime import datetime, timezone
from typing import Callable, Any, Optional, cast, Dict

import aspectlib
from github.GithubException import GithubException, RateLimitExceededException
from github.GithubObject import GithubObject
from github.PaginatedList import PaginatedListBase
from github import Github
from wrapt import synchronized

from ghconf.utils import print_debug, print_info, print_error, ErrorMessage, ttywrite, highlight, resumebar, suspendbar

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
    yield


def checked_weave(*args: Any, **kwargs: Any) -> None:
    for i in range(4):
        if i < 3:
            try:
                aspectlib.weave(*args, **kwargs)
                # every call to weave can load properties which then can make network requests, so we need to check
                # rate limits every time :'(
                check_rate_limits()
            except RateLimitExceededException:
                # sometimes weaving accesses properties on objects which then trigger network requests (yes, really),
                # and then sometimes the buffer in check_rate_limits isn't enough and we get rate limited. In that
                # case, we end up here. You could ask: "Why don't you just handle this exception instead of calling
                # check_rate_limits() all the time?" and the answer is: GitHub seems to penalize tokens that run
                # into the API limit instead of throttling beforehand, so we try to be good.
                if kwargs.get("_nested", False):
                    check_rate_limits()
                    checked_weave(*args, _nested=True, **kwargs)
                else:
                    raise ErrorMessage("We seem to have been rate-limited after trying to outwait the rate limit")
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
                break
        else:
            raise ErrorMessage("3 retries didn't yield results. Exiting.")


def create_recursive_weave_aspect(dry_run: bool = False) -> Any:
    @aspectlib.Aspect(bind=True)
    def recursive_weave(cutpoint: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        ret = yield aspectlib.Proceed
        if isinstance(ret, GithubObject) or isinstance(ret, PaginatedListBase):
            checked_weave(ret, handle_rate_limits, methods=aspectlib.ALL_METHODS)
            if dry_run:
                checked_weave(
                    ret,
                    enforce_dryrun,
                    methods=re.compile(r"(^edit|^remove|^create|^replace)")
                )
            checked_weave(ret, retry_on_server_failure, methods=aspectlib.ALL_METHODS)
            checked_weave(ret, create_recursive_weave_aspect(dry_run), methods=aspectlib.ALL_METHODS)
        yield aspectlib.Return(ret)
    return recursive_weave


@synchronized
def init_github(github_token: str, dry_run: bool = False, *args: Any, **kwargs: Any) -> None:
    global gh

    if not gh:
        print_debug("Initializing Github instance")
        gh = Github(github_token, *args, **kwargs)
        checked_weave(gh, handle_rate_limits)
        if dry_run:
            checked_weave(gh, enforce_dryrun)
        checked_weave(gh, retry_on_server_failure)
        checked_weave(gh, create_recursive_weave_aspect(dry_run))
