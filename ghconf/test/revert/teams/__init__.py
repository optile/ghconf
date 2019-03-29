# -* encoding: utf-8 *-
from typing import Set, Dict, Union

from ghconf.plumbing.teams import Admin, Team, Maintainer, Member, TeamsConfig, BaseMember
from ghconf.plumbing.teams import teamsconfig_t
from ghconf.primitives import EXTEND, OVERWRITE, Policy

config = {
    "organization": {
        "admin_policy": EXTEND,
        "team_policy": OVERWRITE,
        "admins": {
            Admin(username="jdelic"),
        },
    },
    "teams": set(),
}  # type: teamsconfig_t


GhConfTestRevertConfig = TeamsConfig(config)
