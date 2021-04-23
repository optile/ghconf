# -* encoding: utf-8 *-
from typing import Pattern, Dict, List, Union, Set, Any, cast, Callable, TypedDict

from github.GithubException import GithubException
from github.Branch import Branch
from github.Repository import Repository
from github.Organization import Organization
from github.Team import Team as GithubTeam
from github.NamedUser import NamedUser
from typing import Optional

from ghconf import cache
from ghconf.base import GHConfModuleDef, ChangeSet, Change, ChangeMetadata, ChangeActions
from ghconf.github import get_github
from ghconf.primitives import Policy
from ghconf.utils import highlight, print_debug, print_error


# repoaccessdict_t = Dict[str, Union[Policy[Any], List[str]]]
class repoaccessdict_t(TypedDict):
    team_policy: Policy[Any]
    collaborator_policy: Policy[Any]
    teams: List[str]
    collaborators: List[str]

# repoaccessconfig_t = Dict[str, Union[Policy[Any], repoaccessdict_t]]
class repoaccessconfig_t(TypedDict):
    pull: repoaccessdict_t
    push: repoaccessdict_t
    admin: repoaccessdict_t
    policy: Policy[Any]


repoproc_t = Callable[[Organization, Repository, Dict[str, Branch]], List[Change[Any]]]


# singlerepoconfig_t = Dict[str, Union[Policy[Any], List[repoproc_t], repoaccessconfig_t]]
class singlerepoconfig_t(TypedDict):
    access: repoaccessconfig_t
    repo_procs: List[repoproc_t]


repomoduleconfig_t = Dict[Pattern[str], singlerepoconfig_t]


class AccessChangeFactory:
    def __init__(self, org: Organization) -> None:
        super().__init__()
        self.org = org
        self._org_teams = None  # type: Optional[Dict[str, GithubTeam]]

    @property
    def org_teams(self) -> Dict[str, GithubTeam]:
        if self._org_teams is None:
            self._org_teams = {
                ght.name: ght for ght in cache.lazy_get_or_store("orgteams_%s" % self.org.name,
                                                                 lambda: list(self.org.get_teams()))
            }
        return self._org_teams

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

    def apply_team_access(self, change: Change[str], repo: Repository, role: str) -> Change[str]:
        if change.action not in [ChangeActions.ADD, ChangeActions.REMOVE]:
            return change.skipped()

        if change.action == ChangeActions.REMOVE and change.before is not None:
            if change.before in self.org_teams:
                try:
                    self.org_teams[change.before].remove_from_repos(repo)
                except GithubException as e:
                    print_error("Can't remove team %s from repo %s (%s)" %
                                (highlight(change.before), highlight(repo.name), str(e)))
                    return change.failure()
                return change.success()
            else:
                # the team was probably removed by another change
                print_debug("Unknown team %s to remove from repo %s" %
                            (highlight(change.before), highlight(repo.name)))
                return change.success()
        elif change.action == ChangeActions.ADD and change.after is not None:
            if change.after in self.org_teams:
                try:
                    self.org_teams[change.after].set_repo_permission(repo, role)
                except GithubException as e:
                    print_error("Can't set permission %s for team %s on repo %s (%s)" %
                                (highlight(role), highlight(change.after), highlight(repo.name), highlight(str(e))))
                    return change.failure()
                return change.success()
            else:
                print_error("Unknown team %s to add to repo %s" %
                            (highlight(change.after), highlight(repo.name)))
                return change.failure()
        return change.success()

    def apply_collaborator_access(self, change: Change[NamedUser], repo: Repository, role: str) -> Change[NamedUser]:
        if change.action == ChangeActions.REMOVE and change.before is not None:
            try:
                repo.remove_from_collaborators(change.before)
            except GithubException as e:
                print_error("Can't remove collaborator %s from repo %s: %s" %
                            (change.before.login, repo.name, str(e)))
                return change.failure()
            return change.success()
        elif change.action == ChangeActions.ADD and change.after is not None:
            try:
                repo.add_to_collaborators(change.after, self.collaborator_permission_from_unified(role))
            except GithubException as e:
                print_error("Can't add collaborator %s to repo %s: %s" %
                            (change.after.login, repo.name, str(e)))
                return change.failure()
            return change.success()
        return change.skipped()

    def diff_repo_access(self, repo: Repository,
                         access_config: repoaccessconfig_t) -> List[Union[Change[str], Change[NamedUser]]]:
        repo_teams = cache.lazy_get_or_store("repoteams_%s" % repo.name,
                                             lambda: list(repo.get_teams()))  # type: List[GithubTeam]

        current_perms = {
            "pull": set([t.name for t in repo_teams if t.permission == "pull"]),
            "push": set([t.name for t in repo_teams if t.permission == "push"]),
            "admin": set([t.name for t in repo_teams if t.permission == "admin"])
        }

        repo_collabs = cache.lazy_get_or_store("collaborators_%s" % repo.name,
                                               lambda: list(repo.get_collaborators("direct")))  # type: List[NamedUser]
        collab_perms = {
            "push": set(),
            "pull": set(),
            "admin": set(),
        }  # type: Dict[str, Set[NamedUser]]
        for col in repo_collabs:
            perm = self.unified_permission_from_collaborator(repo.get_collaborator_permission(col))
            collab_perms[perm].add(col)

        ret = []  # type: List[Union[Change[str], Change[NamedUser]]]

        default_pol = access_config.get("policy", Policy.OVERWRITE)

        for role in current_perms.keys():
            team_pol = cast(Policy[str],
                            cast(Dict[str, Policy[str]], access_config.get(role, {})).get("team_policy", default_pol))

            if current_perms[role] or cast(Dict[str, List[str]], access_config.get(role, {})).get("teams", []):
                tname_changes = team_pol.apply_to_set(
                    meta=ChangeMetadata(
                        executor=self.apply_team_access,
                        params=[repo, role, ],
                    ),
                    current=current_perms[role],
                    plan=set(cast(List[str],
                                  cast(Dict[str, List[str]], access_config.get(role, {})).get("teams", []))),
                    cosmetic_prefix="%s (team):" % role
                )
                ret += cast(List[Change[str]], tname_changes)

            # assemble a set of NamedUsers for the planned state, because the GitHub collaborator API operates
            # on NamedUser instances, not username strs.
            plan_set = {get_github().get_user(login) for login in
                        cast(Dict[str, List[str]], access_config.get(role, {})).get("collaborators", [])}
            if collab_perms[role] or plan_set:
                collab_pol = cast(Policy[NamedUser],
                                  cast(Dict[str, Policy[NamedUser]],
                                       access_config.get(role, {})).get("collaborator_policy", default_pol))
                collab_changes = collab_pol.apply_to_set(
                    meta=ChangeMetadata(
                        executor=self.apply_collaborator_access,
                        params=[repo, role,],
                    ),
                    current=collab_perms[role],
                    plan=plan_set,
                    cosmetic_prefix="%s (collaborator):" % role
                )
                ret += cast(List[Change[str]], collab_changes)
        return ret


class RepoModule(GHConfModuleDef):
    def __init__(self, repoconfig: repomoduleconfig_t, default: Optional[singlerepoconfig_t] = None) -> None:
        self.config = repoconfig
        self.default_config = default
        self._org_accessfactories = {}  # type: Dict[str, AccessChangeFactory]
        super().__init__()

    def applies_to_repository(self, org: Organization, repo: Repository, branches: List[Branch]) -> bool:
        if self.default_config:
            return True

        for pattern in self.config.keys():
            if pattern.match(repo.name) is not None:
                return True
        return False

    def applies_only_default_config(self, organization: Organization, repo: Repository,
                                    branches: List[Branch]) -> bool:
        for pattern in self.config.keys():
            if pattern.match(repo.name) is not None:
                return False
        return True

    def apply_config(self, config: singlerepoconfig_t, org: Organization, repo: Repository,
                     repo_branches: List[Branch]) -> List[ChangeSet]:
        ret = []
        if "repo_procs" in config:
            branches = {
                branch.name: branch for branch in repo_branches
            }

            changes = []  # type: List[Change[str]]
            for proc in cast(List[repoproc_t], config["repo_procs"]):  # type: repoproc_t
                changes += proc(org, repo, branches)

            if changes:
                cs = ChangeSet(
                    "Repo {name}: Procedures".format(name=repo.name),
                    changes=changes,
                )
                ret.append(cs)

        if "access" in config:
            print_debug("Building %s changes for repo %s" % (highlight("access"), repo.name))

            if org.name is None:
                orgname = "None"
            else:
                orgname = org.name

            if orgname not in self._org_accessfactories:
                # poor man's caching for AccessChangeFactory.org_teams
                self._org_accessfactories[orgname] = AccessChangeFactory(org)

            cs = ChangeSet(
                "Repo {name}: Access".format(name=repo.name),
                self._org_accessfactories[orgname].diff_repo_access(repo, config["access"]),
                description="Changes to access permissions"
            )
            ret.append(cs)

        return ret

    def build_repository_changesets(self, org: Organization, repo: Repository,
                                    repo_branches: List[Branch]) -> List[ChangeSet]:
        ret = []  # type: List[ChangeSet]
        matched = False
        for pattern in self.config.keys():
            if pattern.match(repo.name) is not None:
                matched = True
                print_debug("Repository %s matched by config key %s" %
                            (highlight(repo.name), highlight(pattern.pattern)))
                ret += self.apply_config(self.config[pattern], org, repo, repo_branches)

        if not matched and self.default_config:
            print_debug("Applying %s to repository %s" % (highlight("default config"), highlight(repo.name)))
            ret += self.apply_config(self.default_config, org, repo, repo_branches)

        return ret
