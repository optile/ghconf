# -* encoding: utf-8 *-
from ghconf.plumbing.teams import Admin, Team, Maintainer, Member, TeamsConfig
from ghconf.plumbing.teams import teamsconfig_t
from ghconf.primitives import EXTEND, OVERWRITE

config = {
    "organization": {
        "admin_policy": EXTEND,
        "team_policy": EXTEND,
        "admins": {
            Admin(username="jdelic"),
        },
    },
    "teams": {
        Team(
            name="TopLevelTest",
            description="A test",
            member_policy=OVERWRITE,
            members={
                Maintainer("jdelic"),
                Member("ghconf-test1")
            },
            subteams={
                Team(
                    "Core Developers",
                    description="The Core Developers",
                    member_policy=OVERWRITE,
                    default_permission="push",
                    members={
                        Maintainer("ghconf-test1"),
                        Member("ghconf-test3"),
                    }
                ),
            }
        ),
    }
}  # type: teamsconfig_t


GhConfTestApplyTeams = TeamsConfig(config)
