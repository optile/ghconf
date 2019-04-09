# -* encoding: utf-8 *-

# Useful primitives for building configuration modules and DSLs.
from typing import TypeVar, Dict, Any, Set, List, Generic, Optional, Union, cast

from ghconf.base import Change, ChangeMetadata, ChangeActions


class UnknownPolicyIntention(Exception):
    pass


ST = TypeVar('ST')


class Policy(Generic[ST]):
    """
    A object that represents whether a configuration should be "patched" through the GitHub REST API, leaving
    currently existing configuration intact, or "overwritten", only leaving what is explicitly configured.
    """
    EXTEND = "extend"
    OVERWRITE = "overwrite"

    def __init__(self, intention: str = "extend") -> None:
        if intention not in [Policy.EXTEND, Policy.OVERWRITE]:
            raise ValueError("Policy intention must be one of 'extend', 'overwrite'")
        self.intention = intention

    def __str__(self) -> str:
        return self.intention

    def apply_to_set(self, meta: ChangeMetadata, current: Set[ST], plan: Set[ST],
                     cosmetic_prefix: str = "",
                     single_change: bool = False) -> Union[List[Change[ST]], List[Change[Set[ST]]]]:
        if self.intention == Policy.EXTEND:
            to_add = plan.difference(current)

            if single_change:
                return [
                    cast(
                        Change[Set[ST]],
                        Change(
                            meta=meta,
                            action=ChangeActions.ADD,
                            before=None,
                            after=to_add,
                            cosmetic_prefix=cosmetic_prefix,
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
                ) for addition in to_add]
        elif self.intention == Policy.OVERWRITE:
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


OVERWRITE = Policy(intention=Policy.OVERWRITE)  # type: Policy[Any]
EXTEND = Policy(intention=Policy.EXTEND)  # type: Policy[Any]


class Role:
    """
    All GitHub roles for syntax completion
    """
    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"
    MAINTAINER = "maintainer"


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
