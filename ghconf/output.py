# -* encoding: utf-8 *-
import shutil
from typing import Dict

from colorama import Fore

from ghconf import utils
from ghconf.base import ChangeSet, ChangeAction, ChangeState, ChangeActions
from ghconf.utils import highlight, progressbar, ttywrite, ANSITextWrapper


def print_changeset_banner(changeset: ChangeSet) -> None:
    ttywrite("%s %s\n    (%s %sadditions%s, %s %sdeletions%s, %s %sreplacements%s, %s %sinfos%s)" %
             (highlight("Changes from module"), changeset.source, changeset.additions, Fore.GREEN,
              Fore.RESET, changeset.deletions, Fore.RED, Fore.RESET, changeset.replacements, Fore.YELLOW, Fore.RESET,
              changeset.infos, Fore.LIGHTBLUE_EX, Fore.RESET))
    cols, lines = shutil.get_terminal_size()

    if changeset.description:
        wrapper = ANSITextWrapper(width=cols - 1, initial_indent="  ", subsequent_indent="  ", expand_tabs=True,
                                  tabsize=4)
        ttywrite()
        ttywrite(wrapper.fill(changeset.description))
        ttywrite()


def print_changeset(changeset: ChangeSet) -> None:
    print_changeset_banner(changeset)

    if utils.enable_verbose_output:
        filtered = sorted(changeset.changes)
    else:
        filtered = sorted([c for c in changeset.changes if c.action != ChangeActions.INFO])

    for change in filtered:
        ttywrite("        ", end="")
        ttywrite(str(change))


class Changedict_Stats:
    def __init__(self, adds: int = 0, infos: int = 0, deletes: int = 0, replacements: int = 0):
        self.adds = adds
        self.infos = infos
        self.deletes = deletes
        self.replacements = replacements

    @staticmethod
    def from_changedict(changedict: Dict[str, ChangeSet]) -> 'Changedict_Stats':
        ret = Changedict_Stats()
        for m, cs in changedict.items():
            if cs.additions > 0 or cs.deletions > 0 or cs.replacements > 0 \
                    or cs.infos > 0 or utils.enable_verbose_output:
                ret.adds += cs.additions
                ret.deletes += cs.deletions
                ret.replacements += cs.replacements
                ret.infos += cs.infos
        return ret

    def count(self) -> int:
        return self.adds + self.infos + self.replacements + self.deletes


def print_changedict(changedict: Dict[str, ChangeSet]) -> None:
    s = Changedict_Stats.from_changedict(changedict)

    for m, cs in changedict.items():
        if cs.additions > 0 or cs.deletions > 0 or cs.replacements > 0 or utils.enable_verbose_output:
            ttywrite()
            print_changeset(cs)
    ttywrite()
    ttywrite("Combined: %s (%s %sadditions%s, %s %sdeletions%s, %s %sreplacements%s, %s %sinfos%s)" %
             (s.count(), s.adds, Fore.GREEN, Fore.RESET, s.deletes, Fore.RED, Fore.RESET,
              s.replacements, Fore.YELLOW, Fore.RESET, s.infos, Fore.LIGHTBLUE_EX, Fore.RESET))


def apply_changeset(changeset: ChangeSet) -> Dict[str, int]:
    cols, lines = shutil.get_terminal_size()
    fmt = "        {{change:.<{left}}}{{status:.>20}}".format(left=cols-30)
    print_changeset_banner(changeset)
    results = {}  # type: Dict[str, int]
    for change in changeset.changes:
        change.execute()
        ttywrite(fmt.format(change=str(change), status=str(change.status)))
        if str(change.status.status) not in results:
            results[str(change.status.status)] = 0
        results[str(change.status.status)] += 1
    return results


def apply_changedict(changedict: Dict[str, ChangeSet]) -> None:
    s = Changedict_Stats.from_changedict(changedict)
    pbar = None
    if utils.enable_progressbar:
        pbar = progressbar(total=s.count())
    results = {}  # type: Dict[str, int]
    for m, cs in changedict.items():
        csres = apply_changeset(cs)
        for k, v in csres.items():
            if k in results:
                results[k] += v
            else:
                results[k] = v
        if utils.enable_progressbar and pbar:
            pbar.update(cs.count())
        ttywrite()

    cols, lines = shutil.get_terminal_size()
    ttywrite("=" * (cols - 15))
    ttywrite("    Results")
    ttywrite("=" * (cols - 15))
    for k, v in results.items():
        ttywrite("    {count:>4}    {state} changes".format(count=v, state=k))
