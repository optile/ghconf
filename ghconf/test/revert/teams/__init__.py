# -* encoding: utf-8 *-
from ghconf.plumbing.teams import TeamsModule, Admin
from ghconf.plumbing.teams import teamsmoduleconfig_t
from ghconf.primitives import Policy

config = {
    "organization": {
        "admin_policy": Policy.EXTEND,
        "team_policy": Policy.OVERWRITE,
        "admins": {
            Admin(username="jdelic"),
        },
    },
    "teams": set(),
}  # type: teamsmoduleconfig_t


GhConfTestRevertConfig = TeamsModule(config)
