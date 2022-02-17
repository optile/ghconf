#!/usr/bin/python3 -u
# -* encoding: utf-8 *-
import os
import re
import shutil

import sys
import threading
import time
from concurrent.futures import Future
from concurrent.futures import ThreadPoolExecutor
from re import error

from argparse import ArgumentParser, SUPPRESS, Namespace
from typing import Dict, List, Tuple
from typing import Optional

import tqdm

from ghconf import utils, github as ghcgithub
from ghconf.base import GHConfModuleDef, ChangeSet, Change
from ghconf.output import print_changedict, ChangedictStats, print_changeset_banner, format_changeset_banner, \
    print_lines

from github import GithubException
from github.Organization import Organization
from github.Repository import Repository

from ghconf.utils import print_debug, progressbar, print_info, print_warning, print_error, print_wrapped, prompt, \
    ttywrite
from ghconf.utils.threading import ThreadEx, KillSwitchReceived

modules = {}  # type: Dict[str, GHConfModuleDef]


def assemble_repolist(args: Namespace, org: Organization) -> List[Repository]:
    repolist = []
    filtered_repolist = []
    if not args.skip_repo_changes:
        print_info("Assembling repository list...")
        if args.repos:
            for reponame in args.repos:
                try:
                    r = org.get_repo(reponame)
                    repolist.append(r)
                except GithubException:
                    raise utils.ErrorMessage("Repository %s not found. At least with this API key." %
                                             utils.highlight(reponame))

        if args.reporegexes or (not args.repos and not args.reporegexes):
            allrepos = list(org.get_repos())
            if args.reporegexes:
                for reporegex in args.reporegexes:
                    print_debug("Matching regex %s" % utils.highlight(reporegex))
                    try:
                        regex = re.compile(reporegex)
                    except error as e:
                        raise utils.ErrorMessage("Not a valid regular expression %s (%s)" %
                                                 (utils.highlight(reporegex), str(e)))
                    for repo in allrepos:
                        if regex.match(repo.name):
                            repolist.append(repo)

        if not args.repos and not args.reporegexes:
            print_info("No repository regex or name specified, run against %s repos" % utils.highlight("all"))
            repolist = list(org.get_repos())

        filtered_repolist = [r for r in repolist if not r.archived]

        if not filtered_repolist:
            if args.skip_org_changes:
                print_warning("No repos matched and skipping org changes. Nothing to do.")
            else:
                print_warning("No repos matched!")

    return filtered_repolist


def assemble_changedict(args: Namespace, org: Organization, github_token: str) -> Dict[str, ChangeSet]:
    changedict = {}
    if args.skip_org_changes:
        print_warning("Skipping org changes (as per --no-org-changes)")
    else:
        pbar = None
        if utils.enable_progressbar:
            pbar = progressbar(len(modules))

        for modulename, moduledef in modules.items():  # type: str, GHConfModuleDef
            if utils.enable_progressbar and pbar:
                pbar.update()
            try:
                print_info("Building org changeset for %s" % modulename)
                cslist = moduledef.build_organization_changesets(org)
                for cs in cslist:
                    changedict.update(cs.todict())
            except NotImplementedError:
                print_debug("%s does not support creating an organization changeset. It might not modify the "
                            "org at all or it might just not report it." % utils.highlight(modulename))
        if pbar:
            pbar.close()

    capcache = {}  # type: Dict[str, bool]
    repolist = assemble_repolist(args, org)

    if not repolist:
        return changedict

    pbar = None
    repocount = len(repolist)
    repofmt = "{{ix:>{len}}}/{count} Processing repo {{repo}}".format(len=len(str(repocount)), count=str(repocount))
    if utils.enable_progressbar:
        pbar = progressbar(repocount)

    with ThreadPoolExecutor(max_workers=args.worker_count) as executor:
        cslist_futures = []  # type: List[Future]
        for ix, repo in enumerate(repolist):

            def _thread_executor(_ix: int, orgname: str, reponame: str) -> List[ChangeSet]:
                _thl_org = ghcgithub.get_org(orgname, github_token)
                _thl_repo = _thl_org.get_repo(reponame)
                branches = list(_thl_repo.get_branches())

                if utils.enable_progressbar:
                    pbar.update()

                if utils.enable_verbose_output:
                    print_info(repofmt.format(ix=_ix + 1, repo=_thl_repo.full_name))

                cslist = []  # type: List[ChangeSet]
                for modulename, moduledef in modules.items():
                    if not capcache.get(modulename, True):
                        print_debug("Capability cache for module %s indicates no support for repos" % modulename)
                        continue

                    try:
                        print_debug("Building repo changeset for %s => %s" % (modulename, reponame))
                        _csl = moduledef.build_repository_changesets(_thl_org, _thl_repo, branches)
                        cslist += _csl
                    except NotImplementedError:
                        print_debug("%s does not support creating a repo changeset for repo %s. It might just not "
                                    "make any modifications at all or it might not report them." %
                                    (utils.highlight(modulename), utils.highlight(reponame)))
                        capcache[modulename] = False
                        continue
                return cslist

            cslist_futures.append(
                executor.submit(_thread_executor, ix, org.login, repo.name)
            )

        for csf in cslist_futures:
            _csl = csf.result()
            if ghcgithub.killswitch.is_set():
                raise KillSwitchReceived()
            for cs in _csl:
                changedict.update(cs.todict())

    if pbar:
        pbar.close()
    return changedict


def apply_changeset(changeset: ChangeSet, pbar: tqdm.tqdm,
                    executor: ThreadPoolExecutor) -> Tuple[Dict[str, int], List[Future], List[str]]:
    cols, lines = shutil.get_terminal_size()
    fmt = "        {{change:.<{left}}}{{status:.>20}}".format(left=cols-30)
    results_lock = threading.Lock()
    results = {}  # type: Dict[str, int]

    futures = []  # type: List[Future]
    banner = format_changeset_banner(changeset)
    for change in changeset.changes:
        def _threadexecutor(change: Change) -> str:
            change.execute()
            if utils.enable_progressbar and pbar:
                pbar.update()
            with results_lock:
                if str(change.status.status) not in results:
                    results[str(change.status.status)] = 0
                results[str(change.status.status)] += 1

            return fmt.format(change=str(change), status=str(change.status))

        futures.append(executor.submit(_threadexecutor, change))

    return results, futures, banner


def apply_changedict(args: Namespace, changedict: Dict[str, ChangeSet]) -> None:
    s = ChangedictStats.from_changedict(changedict)
    pbar = None
    if utils.enable_progressbar:
        pbar = progressbar(total=s.count())
    results = {}  # type: Dict[str, int]
    cs_futures = []  # type: List[Future]
    with ThreadPoolExecutor(max_workers=args.worker_count) as executor:
        for m, cs in changedict.items():
            cs_futures.append(
                executor.submit(apply_changeset, cs, pbar, executor)
            )

        for fut in cs_futures:
            _res = fut.result()  # type: Tuple[Dict[str, int], List[Future], List[str]]
            csres, subfuts, lines = _res
            for sf in subfuts:
                lines.append(sf.result())

            for k, v in csres.items():
                if k in results:
                    results[k] += v
                else:
                    results[k] = v

            print_lines(lines)

    cols, lines = shutil.get_terminal_size()
    ttywrite("=" * (cols - 15))
    ttywrite("    Results")
    ttywrite("=" * (cols - 15))
    for k, v in results.items():
        ttywrite("    {count:>4}    {state} changes".format(count=v, state=k))


def main() -> None:
    module_parser = ArgumentParser(add_help=False)
    module_parser.add_argument("-m", "--module", action="append", dest="modules", default=[], help=SUPPRESS)
    module_parser.add_argument("--debug", action="store_true", dest="debug", default=False)
    module_parser.add_argument("--no-color", action="store_true", dest="no_color", default=False)
    preargs, _ = module_parser.parse_known_args()

    utils.enable_debug_output = preargs.debug
    utils.init_color(preargs.no_color)

    if preargs.modules:
        import importlib
        for module in preargs.modules:  # type: str
            if ":" in module:
                module, entrypoint_name = module.split(":", 1)
            else:
                entrypoint_name = "entry_point"
            try:
                print_debug("Loading module %s:%s" % (module, entrypoint_name))
                mod = importlib.import_module(module)
                if hasattr(mod, entrypoint_name):
                    entrypoint = getattr(mod, entrypoint_name)
                    try:
                        i = iter(entrypoint)
                        mods = entrypoint
                    except TypeError:
                        mods = [entrypoint]

                    for ep in mods:
                        if isinstance(ep, type):
                            try:
                                modules["%s::%s" % (module, ep.__class__.__name__)] = ep()
                            except Exception as e:
                                raise utils.ErrorMessage("Unable to instantiate `entry_point` for module %s" %
                                                         module) from e
                        elif isinstance(ep, GHConfModuleDef):
                            modules["%s::%s" % (module, ep.__class__.__name__)] = ep
                        else:
                            raise utils.ErrorMessage("Module entry point %s is neither an instance of GHConfModuleDef, "
                                                     "a list of GHConfModuleDef or a subclass of GHConfModuleDef." %
                                                     module)
                else:
                    raise utils.ErrorMessage("Module %s has no `entry_point` top-level variable" % module)
            except ImportError as e:
                raise utils.ErrorMessage("Can't import module %s (use --debug for more information)" % module) from e

    parser = ArgumentParser(description="ghconf is a tool that parses declarative configuration files in a Python DSL "
                                        "and then runs Python modules against a preconfigured PyGithub instance. This "
                                        "allows us to apply common GitHub configuration through GitHub's v3 REST API "
                                        "to all repositories that are part of our organization.")

    parser.add_argument("-o", "--organization", dest="org", default="optile",
                        help="The GitHub organization to run against. The GitHub API token must have write access to "
                             "this organization.")
    parser.add_argument("-r", "--repo", dest="repos", action="append", default=[],
                        help="Specify one or more repositories to run the configuration against. (Optional. If not "
                             "specified, changes will be made to all repos in the org as modules see fit.)")
    parser.add_argument("-re", "--repo-regex", dest="reporegexes", action="append", default=[],
                        help="Specify one or more regular expressions to match repositories to run the configuration "
                             "against. (Optional. If not specified, changes will be made to all repos in the org as "
                             "modules see fit.)")
    parser.add_argument("--no-repo-changes", dest="skip_repo_changes", action="store_true", default=False,
                        help="When set, ghconf will only execute org level changes.")
    parser.add_argument("--no-org-changes", dest="skip_org_changes", action="store_true", default=False,
                        help="When set, ghconf will not execute org level changes.")
    parser.add_argument("--github-token", dest="github_token", default=None,
                        help="A GitHub API token for the user specified through '--github-user' to use for accessing "
                             "the GitHub API. (Envvar: GITHUB_TOKEN)")
    parser.add_argument("--module", dest="modules", action="append", default=[], required=True,
                        help="Specify Python modules as configuration that will be imported by ghconf.")
    parser.add_argument("--debug", dest="debug", action="store_true", default=False,
                        help="Enable debug output about API interactions.")
    parser.add_argument("--list-unconfigured-repos", dest="list_unconfigured", action="store_true", default=False,
                        help="List the names of all repositories that remain untouched with the current configuration")
    parser.add_argument("-v", "--verbose", dest="verbose", action="store_true", default=False,
                        help="Verbose output. Include informational output, like objects that don't change.")
    parser.add_argument("--no-color", dest="no_color", action="store_true", default=False,
                        help="Don't output ANSI colors")
    parser.add_argument("--no-progressbar", dest="no_progressbar", action="store_true", default=False,
                        help="Skip the progress bar")
    parser.add_argument("--plan", dest="plan", action="store_true", default=False,
                        help="Evaluate all changes and show what the tool would change with the current configuration.")
    parser.add_argument("--execute", dest="execute", action="store_true", default=False,
                        help="Execute any detected changes without asking first. If this is not set, ghconf will ask "
                             "for permission before executing any changes.")
    parser.add_argument("-w", "--workers", dest="worker_count", type=int, default=10,
                        help="Number of worker threads used to parallelize work with GitHub's API (default: 10).")

    for modulename, moduledef in modules.items():  # type: str, GHConfModuleDef
        try:
            print_debug("Add args for %s" % modulename)
            moduledef.add_args(parser)
        except NotImplementedError:
            pass

    # parser.parse_args might just execute the HelpCommand action and start writing to stdout,
    # so we flush the output thread. This doesn't solve the race condition, _except_ that we
    # know that at this point in the program there is no other thread producing output.
    utils.flush_output()
    args = parser.parse_args(sys.argv[1:])

    if args.verbose:
        utils.enable_verbose_output = True

    utils.enable_progressbar = not args.no_progressbar

    if args.github_token:
        ghtoken = args.github_token
    elif os.getenv("GITHUB_TOKEN"):
        ghtoken = os.getenv("GITHUB_TOKEN")
    else:
        raise utils.ErrorMessage("'--github-token' or environment variable GITHUB_TOKEN must be set")

    for modulename, moduledef in modules.items():
        try:
            print_debug("Validate args for %s" % modulename)
            moduledef.validate_args(args)
        except NotImplementedError:
            pass

    try:
        print_debug("Initialize GitHub API, load organization")
        org = ghcgithub.get_org(args.org, ghtoken, args.plan)
    except GithubException:
        raise utils.ErrorMessage("No such GitHub organization %s for the given API token" % args.org)

    if args.plan:
        # banner
        print_info("=" * (shutil.get_terminal_size()[0] - 15))
        print_info("{{:^{width}}}".format(width=shutil.get_terminal_size()[0] - 15).format("Plan mode"))
        print_info("=" * (shutil.get_terminal_size()[0] - 15))
        ###

        print_changedict(assemble_changedict(args, org, ghtoken))
    elif args.list_unconfigured:
        print_info("=" * (shutil.get_terminal_size()[0] - 15))
        print_info("{{:^{width}}}".format(width=shutil.get_terminal_size()[0] - 15).format("Unconfigured repositories"))
        print_info("=" * (shutil.get_terminal_size()[0] - 15))

        repolist = assemble_repolist(args, org)
        if repolist:
            pbar = progressbar(len(repolist) * len(modules))
            for repo in repolist:
                branches = list(repo.get_branches())
                for modulename, moduledef in modules.items():
                    pbar.update()
                    try:
                        if moduledef.applies_to_repository(org, repo, branches):
                            repo.ghconf_touched = True
                            if not hasattr(repo, 'only_default'):
                                repo.only_default = {}
                            repo.only_default[modulename] = moduledef.applies_only_default_config(org, repo, branches)
                    except NotImplementedError:
                        continue
                if not hasattr(repo, "ghconf_touched"):
                    repo.ghconf_touched = False
                    repo.only_default = {}

            pbar.close()

            touched = []
            for repo in repolist:
                if not repo.ghconf_touched or all([v for k, v in repo.only_default.items()]):
                    touched.append(repo.name)

            for s in sorted(touched):
                print_wrapped(s)
    else:
        # banner
        print_info("=" * (shutil.get_terminal_size()[0] - 15))
        print_info(
            "{{:^{width}}}".format(width=shutil.get_terminal_size()[0] - 15).format(utils.highlight("Execute mode"))
        )
        print_info("=" * (shutil.get_terminal_size()[0] - 15))
        ###
        changedict = assemble_changedict(args, org, ghtoken)
        if not args.execute:
            print_changedict(changedict)
            choice = prompt("Proceed and execute? [y/N] ", choices=["y", "n"], default="n")
            if choice != "y":
                print_info("Execution cancelled")
                return

        apply_changedict(args, changedict)


def app() -> None:
    wt = None  # type: Optional[ThreadEx]
    mt = None  # type: Optional[ThreadEx]
    try:
        wt = ThreadEx(target=utils.ttywriter, args=(mt.is_alive,), daemon=True)
        wt.start()

        mt = ThreadEx(target=main, daemon=True)
        mt.start()

        # why don't you just .join() the above threads? Because then on Windows
        # CTRL+C stops working as CPython.win64 blocks in SleepConditionVariableSRW
        # which is uninterruptible. This has been your Python internals lesson
        # of the day. The above threads are daemon threads, so they die when the
        # while-loop exits.
        while mt.is_alive() and wt.is_alive():
            time.sleep(0.01)

        # finish all output
        if mt.has_exception():
            # mt is doing a lot of stuff, joining it here if it has no exception
            # might actually end up blocking indefinitely on Windows, so we don't. When we
            # exit, it'll be taken down. But if it has an exception then ThreadEx.join will
            # bubble it into this thread, which we want so we handle ErrorMessage correctly.
            mt.join()
        wt.join()

        if utils.enable_debug_output:
            print()
            print("========= API Operations =========")
            print("Available at start: %-9s" % ghcgithub.ratelimit_high)
            print("Remaining at end:  %-9s" % ghcgithub.ratelimit_low)
            print("Account limit: %-9s" % ghcgithub.ratelimit_limit)
    except utils.ErrorMessage as e:
        ghcgithub.killswitch.set()
        print_error("%s" % e.ansi_msg)
        utils.close_ttywriter()
        wt.join()

        if utils.enable_debug_output:
            print(utils.highlight("********** VERBOSE OUTPUT Full Exception Follows **********"))
            raise
        else:
            sys.exit(e.exitcode)
    except KeyboardInterrupt:
        ghcgithub.killswitch.set()
        utils.close_ttywriter()
        mt.join()
        wt.join()
        print("\n\nCtrl+C break received. Exiting.")
        return


if __name__ == "__main__":
    app()
