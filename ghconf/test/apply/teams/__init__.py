# -* encoding: utf-8 *-
from ghconf.plumbing.teams import Admin, Team, Maintainer, Member, TeamsModule, teamsmoduleconfig_t
from ghconf.primitives import Policy

config = {
    "organization": {
        "admin_policy": Policy.EXTEND,
        "team_policy": Policy.EXTEND,
        "admins": {
            Admin(username="jdelic"),
        },
    },
    "teams": {
        Team(
            name="TopLevelTest",
            description="A test",
            member_policy=Policy.OVERWRITE,
            members={
                Maintainer("jdelic"),
                Member("ghconf-test1")
            },
            subteams={
                Team(
                    "Core Developers",
                    description="The Core Developers",
                    member_policy=Policy.OVERWRITE,
                    default_permission="push",
                    members={
                        Maintainer("ghconf-test1"),
                        Member("ghconf-test3"),
                    }
                ),
            }
        ),
    }
}  # type: teamsmoduleconfig_t


GhConfTestApplyTeams = TeamsModule(config)
