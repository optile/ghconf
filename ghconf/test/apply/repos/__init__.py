# -* encoding: utf-8 *-
import re

from ghconf.plumbing.repositories import RepositoriesConfig, repoconfig_t
from ghconf.plumbing.repositories import common_procs
from ghconf.primitives import OVERWRITE, EXTEND

config = {
    re.compile(r'^test1[_\-]'): {
        'access': {
            'policy': OVERWRITE,
            'admin': {
                'team_policy': OVERWRITE,
                'collaborator_policy': EXTEND,
                'collaborators': ['ghconf-test4'],
            },
            'push': {
                'teams': ['Core Developers'],
            },
            'pull': {
                'teams': [
                    'TopLevelTest',
                ]
            },
        },
        'repo_procs': [
            common_procs.protect_pr_branch_with_approvals(1),
            common_procs.set_repo_features(),
            common_procs.force_master_default_if_no_develop,
            common_procs.make_develop_default,
            common_procs.protect_pr_branch_with_tests_if_any_exist,
        ],
    },
}  # type: repoconfig_t


GhConfTestRepoApply = RepositoriesConfig(config)
