# -* encoding: utf-8 *-
from typing import Pattern, Dict, List, Union, Set, Any, cast, Callable

from github.GithubException import GithubException
from github.Branch import Branch
from github.Repository import Repository
from github.Organization import Organization
from github.Team import Team as GithubTeam
from typing import Optional

from ghconf import cache
from ghconf.base import GHConfModuleDef, ChangeSet, Change, ChangeMetadata, ChangeAction, ChangeActions
from ghconf.plumbing.teams import Team
from ghconf.primitives import Policy, OVERWRITE
from ghconf.utils import highlight, ErrorMessage, print_debug, print_warning, print_error, print_info


class AccessChangeFactory:
    def __init__(self, org: Organization) -> None:
        super().__init__()
        self.org = org
        self._org_teams = None  # type: Optional[Dict[str, Team]]

    @property
    def org_teams(self) -> Dict[str, GithubTeam]:
        if self._org_teams is None:
            self._org_teams = {
                ght.name: ght for ght in cache.lazy_get_or_store("orgteams_%s" % self.org.name,
                                                                 lambda: list(self.org.get_teams()))
            }
        return self._org_teams

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

    def diff_team_access(self, repo: Repository,
                         access_config: Dict[str, Dict[str, Union[Policy[Any], List[str]]]]) -> List[Change[str]]:
        repo_teams = cache.lazy_get_or_store("repoteams_%s" % repo.name,
                                             lambda: list(repo.get_teams()))  # type: List[GithubTeam]

        current_perms = {
            "pull": set([t.name for t in repo_teams if t.permission == "pull"]),
            "push": set([t.name for t in repo_teams if t.permission == "push"]),
            "admin": set([t.name for t in repo_teams if t.permission == "admin"])
        }

        ret = []  # type: List[Change[str]]

        default_pol = access_config.get("policy", OVERWRITE)

        for role in current_perms.keys():
            pol = cast(Policy[str], access_config.get(role, {}).get("policy", default_pol))

            tname_changes = pol.apply_to_set(
                meta=ChangeMetadata(
                    executor=self.apply_team_access,
                    params=[repo, role, ],
                ),
                current=current_perms[role],
                plan=set(cast(List[str], access_config.get(role, {}).get("teams", []))),
                cosmetic_prefix="%s:" % role
            )
            ret += cast(List[Change[str]], tname_changes)
        return ret


repoproc_t = Callable[[Organization, Repository, Dict[str, Branch]], List[Change[str]]]
accessconfig_t = Dict[str, Union[Policy[Any], Dict[str, Union[Policy[Any], List[str]]]]]
singleconfig_t = Dict[str, Union[Policy[Any], List[repoproc_t], accessconfig_t]]
repoconfig_t = Dict[Pattern[str], singleconfig_t]


class RepositoriesConfig(GHConfModuleDef):
    def __init__(self, repoconfig: repoconfig_t, default: Optional[singleconfig_t] = None) -> None:
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

    def apply_config(self, config: Dict[Any, Any], org: Organization, repo: Repository,
                     repo_branches: List[Branch]) -> List[ChangeSet]:
        ret = []
        if "repo_procs" in config:
            branches = {
                branch.name: branch for branch in repo_branches
            }

            changes = []  # type: List[Change[str]]
            for proc in config["repo_procs"]:  # type: repoproc_t
                changes += proc(org, repo, branches)

            if changes:
                cs = ChangeSet(
                    "Repo {name}: Procedures".format(name=repo.name),
                    changes=changes,
                )
                ret.append(cs)

        if "access" in config:
            print_debug("Building *access* changes for repo %s" % repo.name)

            if org.name not in self._org_accessfactories:
                # poor man's caching for AccessChangeFactory.org_teams
                self._org_accessfactories[org.name] = AccessChangeFactory(org)

            cs = ChangeSet(
                "Repo {name}: Access".format(name=repo.name),
                self._org_accessfactories[org.name].diff_team_access(repo, config["access"]),
                description="Changes to team permissions"
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
