"""
re.compile(r'^a_repo_name$'): {
        'access': FallbackDict(
            {
                'pull': {
                    'team_policy': EXTEND,
                    'teams': [
                        'team1',
                        'team2',
                        'team3',
                    ],
                    'collaborator_policy': OVERWRITE,
                    'collaborators': [
                        'githubuser',
                    ],
                },
            },
            create_from=default_team_access,
        ),
        'repo_procs': default_repo_procs + protect_pr_branch_plus_review_dismissal(1),
    },

becomes

re.compile(r'^a_repo_name$'): \
    take(default_config) \
        .set_team_policy(PULL, EXTEND) \
        .set_collaborator_policy(PULL, OVERWRITE) \
        .set_access(PULL, teams=['team1', 'team2', 'team3',],
                    collaborators='githubuser')

"""
import copy
from typing import List, Dict, Callable, cast, Protocol
from typing import Set
from typing import Union

from ghconf.plumbing.repositories import repoaccessconfig_t, repoaccessdict_t, singlerepoconfig_t
from ghconf.plumbing.repositories import repoproc_t
from ghconf.primitives import Permission, Policy, PermissionSetType
from ghconf.utils import print_debug
from ghconf.utils.events import event_config_complete

_config_store = {}  # type: Dict[str, RepoConfig]


class GitHubPermissionSet:
    def __init__(self, typ: PermissionSetType, *, pull_policy: Policy = None, pull: Set[str] = None,
                 push_policy: Policy = None, push: Set[str] = None,
                 admin_policy: Policy = None, admin: Set[str] = None) -> None:
        self._type = typ
        self.pull_policy = pull_policy  # type: Union[Policy, None]
        self.push_policy = push_policy  # type: Union[Policy, None]
        self.admin_policy = admin_policy  # type: Union[Policy, None]
        if pull is None:
            self.pull = set()  # type: Set[str]
        else:
            self.pull = pull

        if push is None:
            self.push = set()  # type: Set[str]
        else:
            self.push = push

        if admin is None:
            self.admin = set()  # type: Set[str]
        else:
            self.admin = admin

    def give_pull(self, identifier: str) -> None:
        try:
            self.push.remove(identifier)
            self.admin.remove(identifier)
        except KeyError:
            pass
        self.pull.add(identifier)

    def give_read(self, identifier: str) -> None:
        self.give_pull(identifier)

    def give_push(self, identifier: str) -> None:
        try:
            self.pull.remove(identifier)
            self.admin.remove(identifier)
        except KeyError:
            pass
        self.push.add(identifier)

    def give_write(self, identifier: str) -> None:
        self.give_push(identifier)

    def give_admin(self, identifier: str) -> None:
        try:
            self.push.remove(identifier)
            self.pull.remove(identifier)
        except KeyError:
            pass
        self.admin.add(identifier)

    def give(self, typ: Permission, identifier: str) -> None:
        if typ == Permission.PULL:
            self.give_pull(identifier)
        elif typ == Permission.PUSH:
            self.give_push(identifier)
        elif typ == Permission.ADMIN:
            self.give_admin(identifier)

    def set_policy(self, typ: Permission, policy: Policy) -> None:
        if typ == Permission.PULL:
            self.pull_policy = policy
        elif typ == Permission.PUSH:
            self.push_policy = policy
        elif typ == Permission.ADMIN:
            self.admin_policy = policy

    def to_accessconfig(self, *, default_policy: Policy, override_type: PermissionSetType = None) -> repoaccessconfig_t:
        typ = override_type if override_type is not None else self._type
        typkey = "teams" if typ == PermissionSetType.TEAMS else "collaborators"

        # it's ok to use for_teams here, as accessdicts use standardized push, pull, admin
        # for teams and collaborators alike and ghconf converts to the correct GitHub permission
        # (read, write, push, pull) on-the-fly later
        ret = {
            Permission.PUSH.for_teams(): {
                typkey: list(self.push),  # type: ignore
            },
            Permission.PULL.for_teams(): {
                typkey: list(self.pull),  # type: ignore
            },
            Permission.ADMIN.for_teams(): {
                typkey: list(self.admin),  # type: ignore
            },
        }  # type: ignore

        poltypkey = "team_policy" if typ == PermissionSetType.TEAMS else "collaborator_policy"
        if self.pull_policy is None:
            ret[Permission.PULL.for_teams()][poltypkey] = default_policy  # type: ignore
        else:
            ret[Permission.PULL.for_teams()][poltypkey] = self.pull_policy  # type: ignore
        if self.push_policy is None:
            ret[Permission.PUSH.for_teams()][poltypkey] = default_policy  # type: ignore
        else:
            ret[Permission.PUSH.for_teams()][poltypkey] = self.push_policy  # type: ignore
        if self.admin_policy is None:
            ret[Permission.ADMIN.for_teams()][poltypkey] = default_policy  # type: ignore
        else:
            ret[Permission.ADMIN.for_teams()][poltypkey] = self.admin_policy  # type: ignore
        return cast(repoaccessconfig_t, ret)


class RepoAccessConfig:
    def __init__(self, *, default_policy: Policy = Policy.OVERWRITE, team_policy: Policy = None,
                 collaborator_policy: Policy = None) -> None:
        self.team_policy = team_policy
        self.collaborator_policy = collaborator_policy
        self.default_policy = default_policy
        self.teams = GitHubPermissionSet(PermissionSetType.TEAMS)
        self.collaborators = GitHubPermissionSet(PermissionSetType.COLLABORATORS)

    def to_accessconfig(self) -> repoaccessconfig_t:
        ret = self.teams.to_accessconfig(default_policy=self.default_policy)

        # this works because to_accessconfig returns a dict with all top level keys
        # even if they're empty
        for k in ret:
            ret[k].update(self.collaborators.to_accessconfig(default_policy=self.default_policy)[k])  # type: ignore
        return cast(repoaccessconfig_t, ret)


class RepoConfig:
    def __init__(self) -> None:
        self.access = RepoAccessConfig()
        self.repo_procs = []  # type: List[repoproc_t]

    def to_repoconfig(self) -> singlerepoconfig_t:
        ret = singlerepoconfig_t(
            access=self.access.to_accessconfig(),
            repo_procs=self.repo_procs
        )
        return ret

    def set_access(self, typ: Permission, *, teams: Union[List[str], Set[str], None] = None,
                   collaborators: Union[List[str], Set[str], None] = None) -> 'RepoConfig':
        if teams:
            for t in teams:
                self.access.teams.give(typ, t)
        if collaborators:
            for c in collaborators:
                self.access.collaborators.give(typ, c)
        return self

    def set_default_policy(self, policy: Policy) -> 'RepoConfig':
        self.access.default_policy = policy
        return self

    def set_team_policy(self, policy: Policy, typ: Permission = None) -> 'RepoConfig':
        if typ is None:
            self.access.team_policy = policy
        else:
            self.access.teams.set_policy(typ, policy)
        return self

    def set_collaborator_policy(self, policy: Policy, typ: Permission = None) -> 'RepoConfig':
        if typ is None:
            self.access.collaborator_policy = policy
        else:
            self.access.collaborators.set_policy(typ, policy)
        return self

    def give_team(self, perm: Permission, team: str) -> 'RepoConfig':
        self.access.teams.give(perm, team)
        return self

    def give_collaborator(self, perm: Permission, user: str) -> 'RepoConfig':
        self.access.collaborators.give(perm, user)
        return self

    def store(self, key: str) -> 'RepoConfig':
        global _config_store
        _config_store[key] = self
        return self

    def add_proc(self, proc: repoproc_t) -> 'RepoConfig':
        self.repo_procs.append(proc)
        return self

    def set_procs(self, procs: List[repoproc_t]) -> 'RepoConfig':
        self.repo_procs = procs
        return self


def take(cfg: RepoConfig) -> RepoConfig:
    return copy.deepcopy(cfg)


def load(key: str) -> RepoConfig:
    global _config_store
    if key not in _config_store:
        raise KeyError("Config not in config store (yet?) - %s" % key)
    return take(_config_store[key])
