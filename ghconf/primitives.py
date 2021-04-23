# -* encoding: utf-8 *-

# Useful primitives for building configuration modules and DSLs.
import enum
from typing import TypeVar, Dict, Any, Set, List, Generic, Optional, Union, cast

from ghconf.base import Change, ChangeMetadata, ChangeActions


class UnknownPolicyIntention(Exception):
    pass


ST = TypeVar('ST')


class PolicyIntention(enum.Enum):
    EXTEND = "extend"
    OVERWRITE = "overwrite"


class Policy(Generic[ST]):
    """
    A object that represents whether a configuration should be "patched" through the GitHub REST API, leaving
    currently existing configuration intact, or "overwritten", only leaving what is explicitly configured.
    """
    OVERWRITE: 'Policy'
    EXTEND: 'Policy'

    def __init__(self, intention: PolicyIntention = PolicyIntention.EXTEND) -> None:
        if intention not in [PolicyIntention.EXTEND, PolicyIntention.OVERWRITE]:
            raise ValueError("Policy intention must be one of EXTEND or OVERWRITE")
        self.intention = intention

    def __str__(self) -> str:
        return str(self.intention)

    def __repr__(self) -> str:
        return "Policy<%s>" % self.intention

    def apply_to_set(self, meta: ChangeMetadata, current: Set[ST], plan: Set[ST],
                     cosmetic_prefix: str = "",
                     single_change: bool = False) -> Union[List[Change[ST]], List[Change[Set[ST]]]]:
        if self.intention == PolicyIntention.EXTEND:
            to_add = plan.difference(current)

            if single_change:
                return [
                    Change[Set[ST]](
                        meta=meta,
                        action=ChangeActions.ADD,
                        before=None,
                        after=to_add,
                        cosmetic_prefix=cosmetic_prefix,
                    )
                ]
            else:
                return [Change(
                    meta=meta,
                    action=ChangeActions.ADD,
                    before=None,
                    after=addition,
                    cosmetic_prefix=cosmetic_prefix,
                ) for addition in to_add]
        elif self.intention == PolicyIntention.OVERWRITE:
            to_add = plan.difference(current)
            to_remove = current.difference(plan)
            noops = plan.intersection(current)

            if current == plan:
                return [
                    cast(
                        Change[Set[ST]],
                        Change(
                            meta=meta,
                            action=ChangeActions.INFO,
                            before=current,
                            after=plan,
                            cosmetic_prefix=cosmetic_prefix
                        )
                    )
                ]

            if single_change:
                return [
                    cast(
                        Change[Set[ST]],
                        Change(
                            meta=meta,
                            action=ChangeActions.REPLACE,
                            before=current,
                            after=plan,
                            cosmetic_prefix=cosmetic_prefix
                        )
                    )
                ]
            else:
                return [Change(
                    meta=meta,
                    action=ChangeActions.ADD,
                    before=None,
                    after=addition,
                    cosmetic_prefix=cosmetic_prefix,
                ) for addition in to_add] + [Change(
                    meta=meta,
                    action=ChangeActions.REMOVE,
                    before=deletion,
                    after=None,
                    cosmetic_prefix=cosmetic_prefix,
                ) for deletion in to_remove] + [Change(
                    meta=meta,
                    action=ChangeActions.INFO,
                    before=noop,
                    after=None,
                    cosmetic_prefix=cosmetic_prefix,
                ) for noop in noops]
        raise UnknownPolicyIntention(self.intention)


Policy.OVERWRITE = Policy(intention=PolicyIntention.OVERWRITE)
Policy.EXTEND = Policy(intention=PolicyIntention.EXTEND)


class Role:
    """
    All GitHub roles for syntax completion
    """
    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"
    MAINTAINER = "maintainer"


class PermissionSetType(enum.Enum):
    TEAMS = "teams"
    COLLABORATORS = "collaborators"


class Permission:
    PUSH: 'Permission'
    PULL: 'Permission'
    ADMIN: 'Permission'

    def __init__(self, permstr: str) -> None:
        self.permstr = permstr

    @staticmethod
    def unified_permission_from_collaborator(permstr: str) -> str:
        if permstr == "write" or permstr == "push":
            return "push"
        elif permstr == "read" or permstr == "pull":
            return "pull"
        elif permstr == "admin":
            return "admin"
        else:
            raise ValueError("Unknown permission string to translate: %s" % permstr)

    @staticmethod
    def collaborator_permission_from_unified(permstr: str) -> str:
        if permstr == "push":
            return "write"
        elif permstr == "pull":
            return "read"
        elif permstr == "admin":
            return "admin"
        else:
            raise ValueError("Unknown unified permission to translate: %s" % permstr)

    @staticmethod
    def is_valid(teststr: str) -> bool:
        return teststr in ["push", "pull", "admin", "write", "read"]

    def for_collaborators(self) -> str:
        return Permission.collaborator_permission_from_unified(self.permstr)

    def for_teams(self) -> str:
        return Permission.unified_permission_from_collaborator(self.permstr)

    def value(self, typ: PermissionSetType) -> str:
        if typ == PermissionSetType.TEAMS:
            return Permission.unified_permission_from_collaborator(self.permstr)
        if typ == PermissionSetType.COLLABORATORS:
            return Permission.collaborator_permission_from_unified(self.permstr)
        raise ValueError("Not a valid PermissionSetType %s" % str(typ))

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Permission):
            return self.value(PermissionSetType.TEAMS) == other.value(PermissionSetType.TEAMS)
        elif isinstance(other, str):
            return self.value(PermissionSetType.TEAMS) == other or self.value(PermissionSetType.COLLABORATORS) == other
        return False

    def __str__(self) -> str:
        return self.permstr

    def __repr__(self) -> str:
        return "Permission<%s>" % self.permstr


Permission.PUSH = Permission("push")
Permission.PULL = Permission("pull")
Permission.ADMIN = Permission("admin")

KT = TypeVar('KT')  # Key type.
VT = TypeVar('VT')  # Value type.


class FallbackDict(Dict[KT, VT]):
    """
    A subclass of ``dict`` that assembles its entries from other dicts. This is useful to express
    a hierarchy of configuration where some configuration defaults can be selectively overwritten.

    :param update_with: copied to this dict via update()
    :param create_from: optional initializer dict (values are overwritten from update_with)
    :param fallback_on: if a key is missing from this dict, but exists in ``fallback_on``, the value from
                        ``fallback_on`` is returned. Keep in mind that .keys() and .items() will not enumerate
                          values from ``fallback_on`` even though they will appear to exist in this dict.
    """
    def __init__(self, update_with: Optional[Dict[KT, VT]] = None, create_from: Optional[Dict[KT, VT]] = None,
                 fallback_on: Optional[Dict[KT, VT]] = None, **kwargs: Any) -> None:
        if create_from:
            super().__init__(create_from, **kwargs)
            if update_with:
                self.update(update_with)
            self.update(kwargs)  # type: ignore
        elif update_with:
            super().__init__(update_with, **kwargs)

        if fallback_on:
            self.fallback = fallback_on
        else:
            self.fallback = {}

    def __missing__(self, key: KT) -> Optional[VT]:
        if key in self.fallback:
            return self.fallback[key]
        return None
