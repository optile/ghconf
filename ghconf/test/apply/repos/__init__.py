# -* encoding: utf-8 *-
import re

from ghconf.plumbing.repositories import repomoduleconfig_t, RepoModule
from ghconf.plumbing.repositories import common_procs
from ghconf.plumbing.repositories.dsl import RepoConfig
from ghconf.primitives import Policy, Permission

config = {
    re.compile(r'^test1[_\-]'):
        RepoConfig()
        .set_team_policy(Policy.OVERWRITE, Permission.ADMIN)
        .set_collaborator_policy(Policy.EXTEND)
        .set_access(
            Permission.ADMIN,
            collaborators=['ghconf-test4']
        )
        .set_access(
            Permission.PUSH,
            teams=['Core Developers']
        )
        .set_access(
            Permission.PULL,
            teams=['TopLevelTest']
        )
        .set_procs(
            common_procs.protect_pr_branch_with_approvals(1),
            common_procs.set_repo_features(),
            common_procs.force_master_default_if_no_develop,
            common_procs.make_develop_default,
            common_procs.protect_pr_branch_with_tests_if_any_exist,
        )
        .store("test").to_repoconfig(),
}  # type: repomoduleconfig_t


GhConfTestRepoApply = RepoModule(config)
