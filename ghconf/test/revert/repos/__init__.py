# -* encoding: utf-8 *-
import re

from ghconf.plumbing.repositories import RepoModule, repomoduleconfig_t
from ghconf.plumbing.repositories import common_procs
from ghconf.plumbing.repositories.dsl import RepoConfig
from ghconf.primitives import Policy

config = {
    re.compile(r'^test1[_\-]'):
        RepoConfig()
        .set_team_policy(Policy.OVERWRITE)
        .set_procs([
            common_procs.protect_pr_branch_with_approvals(0),
            common_procs.set_repo_features(enable_wiki=True, enable_issues=True),
            common_procs.force_master_default,
            common_procs.remove_all_status_checks_on_pr_branch,
            common_procs.remove_org_admin_collaborators,
        ]).to_repoconfig(),
}  # type: repomoduleconfig_t


GhConfTestRepoRevert = RepoModule(config)
