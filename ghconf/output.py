# -* encoding: utf-8 *-
import shutil
from typing import Dict, List, Sequence

from colorama import Fore

from ghconf import utils
from ghconf.base import ChangeSet, ChangeActions
from ghconf.utils import highlight, progressbar, ttywrite
from ghconf.utils.ansi import ANSITextWrapper


def print_lines(lines: Sequence[str]) -> None:
    for line in lines:
        ttywrite(line)


def format_changeset_banner(changeset: ChangeSet) -> List[str]:
    lines = [
        "%s %s\n    (%s %sadditions%s, %s %sdeletions%s, %s %sreplacements%s, %s %sinfos%s)" %
        (highlight("Changes from module"), changeset.source, changeset.additions, Fore.GREEN,
        Fore.RESET, changeset.deletions, Fore.RED, Fore.RESET, changeset.replacements, Fore.YELLOW, Fore.RESET,
        changeset.infos, Fore.LIGHTBLUE_EX, Fore.RESET)
    ]

    cols, _ = shutil.get_terminal_size()

    if changeset.description:
        wrapper = ANSITextWrapper(width=cols - 1, initial_indent="  ", subsequent_indent="  ", expand_tabs=True,
                                  tabsize=4)
        lines.append("")
        lines.append(wrapper.fill(changeset.description))
        lines.append("")

    return lines


def print_changeset_banner(changeset: ChangeSet) -> None:
    print_lines(format_changeset_banner(changeset))


def format_changeset(changeset: ChangeSet) -> List[str]:
    lines = format_changeset_banner(changeset)
    if utils.enable_verbose_output:
        filtered = sorted(changeset.changes)
    else:
        filtered = sorted([c for c in changeset.changes if c.action != ChangeActions.INFO])

    for change in filtered:
        lines.append("        %s" % str(change))
    return lines


def print_changeset(changeset: ChangeSet) -> None:
    print_lines(format_changeset(changeset))


class ChangedictStats:
    def __init__(self, adds: int = 0, infos: int = 0, deletes: int = 0, replacements: int = 0):
        self.adds = adds
        self.infos = infos
        self.deletes = deletes
        self.replacements = replacements

    @staticmethod
    def from_changedict(changedict: Dict[str, ChangeSet]) -> 'ChangedictStats':
        ret = ChangedictStats()
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
    s = ChangedictStats.from_changedict(changedict)

    for m, cs in changedict.items():
        if cs.additions > 0 or cs.deletions > 0 or cs.replacements > 0 or utils.enable_verbose_output:
            ttywrite()
            print_changeset(cs)
    ttywrite()
    ttywrite("Combined: %s (%s %sadditions%s, %s %sdeletions%s, %s %sreplacements%s, %s %sinfos%s)" %
             (s.count(), s.adds, Fore.GREEN, Fore.RESET, s.deletes, Fore.RED, Fore.RESET,
              s.replacements, Fore.YELLOW, Fore.RESET, s.infos, Fore.LIGHTBLUE_EX, Fore.RESET))
