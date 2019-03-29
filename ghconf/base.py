# -* encoding: utf-8 *-
from argparse import ArgumentParser, Namespace
from typing import Dict, Union, Callable, Any, List, Optional, TypeVar, Generic, cast, Iterable

from colorama import Fore
from github.Branch import Branch
from github.Organization import Organization
from github.Repository import Repository

from ghconf.utils import enable_color


class ChangeAction:
    """
    nice __str__ rendering of diff-like changes
    """
    def __init__(self, actiontype: str) -> None:
        self.actiontype = actiontype

    def __repr__(self) -> str:
        return self.actiontype

    def __str__(self) -> str:
        def ansistr(color: str) -> str:
            if enable_color:
                return color + str(self.actiontype) + str(Fore.RESET)
            else:
                return str(self.actiontype)

        if self.actiontype == "+":
            return ansistr(Fore.LIGHTGREEN_EX)
        elif self.actiontype == "-":
            return ansistr(Fore.LIGHTRED_EX)
        elif self.actiontype == ">":
            return ansistr(Fore.LIGHTYELLOW_EX)
        else:
            return ansistr(Fore.LIGHTBLUE_EX)


class ChangeActions(ChangeAction):
    """
    An enum of change types
    """
    ADD = ChangeAction("+")
    REMOVE = ChangeAction("-")
    INFO = ChangeAction("=")
    REPLACE = ChangeAction(">")


class ChangeState:
    def __init__(self, status: str) -> None:
        self.status = status

    def __repr__(self) -> str:
        return self.status

    def __str__(self) -> str:
        def ansistr(color: str, override: Optional[str] = None) -> str:
            if enable_color:
                return color + (override or self.status) + str(Fore.RESET)
            else:
                return override or self.status

        if self.status == "pending" or self.status == "skipped":
            return ansistr(Fore.LIGHTBLUE_EX, "OK")
        elif self.status == "successful":
            return ansistr(Fore.GREEN, "OK")
        elif self.status == "failed":
            return ansistr(Fore.RED, "FAILED")
        return "UNKN"


class ChangeStates(ChangeState):
    """
    An enum of change states
    """
    PENDING = ChangeState("pending")  # hasn't been called yet
    SUCCESSFUL = ChangeState("successful")  # change has been executed successfully
    FAILED = ChangeState("failed")  # change has failed
    SKIPPED = ChangeState("skipped")  # no changes were necessary


# this type of callable can apply a change to an Github organization or repo
executor_t = Callable[..., 'Change[Any]']


class ChangeMetadata:
    """
    A wrapper for the metadata necessary to execute a Change. For example: "What team will be the
    parent of the subteam we're adding?". ``context`` should contain any necessary Github API objects
    to make the change.
    :param executor: A callable that, given a PyGithub instance, the Change and it's metadata can execute the Change.
    :param context: A freeform dict of stuff. The executor needs to know what all of it means.
    """
    def __init__(self, executor: executor_t, params: Optional[List[Any]] = None) -> None:
        self.executor = executor
        if params is None:
            self.params = []  # type: List[Any]
        else:
            self.params = params


CT = TypeVar('CT')


class Change(Generic[CT]):
    """
    Is meant to hold a computed change, ie. a change through the Github API that the script intends to make.
    Calling the executor from the ``Change.meta`` together with the Change instance and it's context should
    perform the change on the Github API.
    """
    def __init__(self, meta: ChangeMetadata, action: ChangeAction, cosmetic_prefix: str = "",
                 before: Optional[CT] = None,
                 after: Optional[CT] = None) -> None:
        self.meta = meta
        self.action = action
        self.cosmetic_prefix = cosmetic_prefix
        self.before = before
        self.after = after
        self.status = ChangeStates.PENDING

    @property
    def sortweight(self) -> int:
        if self.action == ChangeActions.REMOVE:
            return 1
        if self.action == ChangeActions.INFO:
            return 2
        if self.action == ChangeActions.REPLACE:
            return 3
        if self.action == ChangeActions.ADD:
            return 4
        return 0

    def __repr__(self) -> str:
        return "Change<%s '%s' '%s'>" % (self.action, self.partstr(self.before), self.partstr(self.after))

    def partstr(self, item: Union[CT, Iterable[CT], Optional[CT]]) -> str:
        if item is None:
            return "<None>"
        elif (isinstance(item, set) or isinstance(item, list) or isinstance(item, dict)) and not item:
            return "<Empty>"
        else:
            if isinstance(item, set) or isinstance(item, list):
                return ", ".join([str(i) for i in item])
            return str(item)

    def execute(self) -> 'Change[CT]':
        return self.meta.executor(self, *self.meta.params)

    def success(self) -> 'Change[CT]':
        self.status = ChangeStates.SUCCESSFUL
        return self

    def failure(self) -> 'Change[CT]':
        self.status = ChangeStates.FAILED
        return self

    def skipped(self) -> 'Change[CT]':
        self.status = ChangeStates.SKIPPED
        return self

    def __str__(self) -> str:
        return "{action}{cosmetics}{before}{after}".format(
            action="%s " % str(self.action),
            cosmetics="%s " % self.cosmetic_prefix if self.cosmetic_prefix else "",
            before=self.partstr(self.before),
            after=" -> %s" % self.partstr(self.after) if self.after is not None else ""
        )

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Change):
            return NotImplemented

        other = cast(Change[CT], other)
        if (self.action == other.action and
                self.before == other.before and
                self.after == other.after):
            return True
        return False

    def __lt__(self, other: 'Change[CT]') -> bool:
        return other.sortweight - self.sortweight > 0

    def __gt__(self, other: 'Change[CT]') -> bool:
        return other.sortweight - self.sortweight < 0


class ChangeSet:
    def __init__(self, source: str, changes: List[Change[Any]], description: Optional[str] = None) -> None:
        self.source = source
        self._changes = changes
        self.description = description

    def _count_type(self, atype: ChangeAction) -> int:
        i = 0
        for c in self.changes:
            if c.action.actiontype == atype.actiontype:
                i = i + 1
        return i

    @property
    def additions(self) -> int:
        return self._count_type(ChangeActions.ADD)

    @property
    def deletions(self) -> int:
        return self._count_type(ChangeActions.REMOVE)

    @property
    def infos(self) -> int:
        return self._count_type(ChangeActions.INFO)

    @property
    def replacements(self) -> int:
        return self._count_type(ChangeActions.REPLACE)

    def count(self) -> int:
        return len(self._changes)

    @property
    def changes(self) -> List[Change[Any]]:
        return sorted(self._changes) if self._changes else []

    @changes.setter
    def changes(self, changes: List[Change[Any]]) -> None:
        self._changes = changes

    def __str__(self) -> str:
        return "ChangeSet by %s <%s changes, %s additions, %s replacements, %s deletions>" % \
               (self.source, len(self.changes), self.additions, self.replacements, self.deletions)

    def todict(self) -> Dict[str, 'ChangeSet']:
        return {
            self.source: self
        }


class GHConfModuleDef:
    """
    This is the abstract base class for modules that can be loaded by ``ghconf --module``.
    """
    def __init__(self) -> None:
        pass

    def add_args(self, parser: ArgumentParser) -> None:
        raise NotImplementedError

    def validate_args(self, args: Namespace) -> None:
        raise NotImplementedError

    def applies_to_repository(self, organization: Organization, repository: Repository, branches: List[Branch]) -> bool:
        """
        Should return True if this module wants to make changes to this repository based off the passed information.
        Implementations of this method should avoid making additional calls.
        :param organization:
        :param repo:
        :param branches:
        :return: True if the module wants to modify this repository
        """
        raise NotImplementedError

    def build_organization_changesets(self, organization: Organization) -> List[ChangeSet]:
        raise NotImplementedError

    def build_repository_changesets(self, organization: Organization, repository: Repository,
                                    branches: List[Branch]) -> List[ChangeSet]:
        """
        If possible, the module should use the API to figure out what it will change and return a ChangeSet that
        :param organization:
        :param repository:
        :param branches:
        :return:
        """
        raise NotImplementedError
