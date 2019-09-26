# -* encoding: utf-8 *-
from typing import Union, Any, Dict, List, Set, Optional

from github.GithubException import GithubException
from github.Organization import Organization
from github.Team import Team as GithubTeam

from ghconf import cache
from ghconf.base import GHConfModuleDef, Change, ChangeSet, ChangeMetadata, ChangeActions
from ghconf.primitives import Policy, EXTEND, Role, OVERWRITE
from ghconf.utils import ErrorMessage, print_debug, print_warning, print_info, print_error, highlight


class BaseMember:
    def __init__(self, *, username: str, role: str, id: Any = None) -> None:
        self.username = username
        self.role = role
        self.id = id

    def __str__(self) -> str:
        return "{role}<{username}{id}>".format(role=self.role, username=self.username,
                                               id=", id={id}".format(id=self.id) if self.id else "")

    def __eq__(self, other: object) -> bool:
        if other is None or not isinstance(other, self.__class__):
            return False
        return self.username.lower() == other.username.lower() and self.role == other.role

    def __hash__(self) -> int:
        return hash((self.username.lower(), self.role))


class Team:
    def __init__(self, name: str, description: str = "", team_policy: Policy['Team'] = EXTEND,
                 member_policy: Policy['BaseMember'] = EXTEND, slug: Optional[str] = None,
                 members: Optional[Set[BaseMember]] = None, subteams: Optional[Set['Team']] = None,
                 default_permission: str = "pull", privacy: str = "closed", id: Optional[int] = None) -> None:
        self.id = id
        self.name = name
        self.description = description
        self.team_policy = team_policy
        self.member_policy = member_policy
        self.default_permission = default_permission
        self.privacy = privacy

        if slug:
            self.slug = slug
        else:
            self.slug = name.lower().replace(" ", "-")

        if members:
            self._members = members
        else:
            self._members = set()

        if subteams:
            self.subteams = subteams
        else:
            self.subteams = set()

    def __eq__(self, other: object) -> bool:
        if other is None or not isinstance(other, self.__class__):
            print_debug("Comparison with different class (Team vs. {})".format(other.__class__))
            return False

        # it's by design that this doesn't compare attributes like default_permission and privacy as these
        # attributes are compared separately and they don't distinguish two Team instances to the point
        # of being entirely different teams
        metadata_eq = self.name == other.name and self.slug == other.slug
        return metadata_eq

    def __hash__(self) -> int:
        ct = (
            self.name,
            self.slug,
        )
        return hash(ct)

    def __str__(self) -> str:
        return "Team<{slug}, id={id}, name=\"{name}\", {mem} members, {st} subteams>".format(
            slug=self.slug, name=self.name, id=self.id, mem=len(self.get_all_members()), st=len(self.subteams))

    @property
    def members(self) -> Set[BaseMember]:
        return self._members - self.get_subteam_members()

    def add_member(self, member: BaseMember) -> None:
        self._members.add(member)

    def get_all_members(self) -> Set[BaseMember]:
        all = self._members
        if self.subteams:
            for st in self.subteams:
                all = all.union(st.get_all_members())
        return all

    def get_subteam_members(self, top: bool = True) -> Set[BaseMember]:
        # we can't trust self._members, since GitHub returns all members (including subteams)
        if top:
            all = set()  # type: Set[BaseMember]
        else:
            all = self._members
        if self.subteams:
            for st in self.subteams:
                all = all.union(st.get_subteam_members(False))
        return all

    def get_all_subteams(self) -> Set['Team']:
        all = self.subteams
        for st in self.subteams:
            all = all.union(st.get_all_subteams())
        return all

    @staticmethod
    def from_githubteam(ght: GithubTeam, *, retrieve_subteams: bool = False,
                        team_policy: Optional[Policy['Team']] = None,
                        member_policy: Optional[Policy['BaseMember']] = None) -> 'Team':
        ret = Team(
            ght.name,
            description=ght.description,
            id=ght.id,
            privacy=ght.privacy,
            default_permission=ght.permission,
            slug=ght.slug,
        )

        if team_policy:
            ret.team_policy = team_policy

        if member_policy:
            ret.member_policy = member_policy

        for m in cache.lazy_get_or_store("teammembers_%s" % ght.name, lambda: list(ght.get_members("member"))):
            ret.add_member(Member(username=m.login, id=m.id))

        for m in cache.lazy_get_or_store("teammaintainers_%s" % ght.name, lambda: list(ght.get_members("maintainer"))):
            ret.add_member(Maintainer(username=m.login, id=m.id))

        if retrieve_subteams:
            for subteam in cache.lazy_get_or_store("subteams_%s" % ght.name, lambda: list(ght.get_subteams())):
                ret.subteams.add(Team.from_githubteam(subteam))

        return ret


class Admin(BaseMember):
    def __init__(self, username: str, id: Optional[int] = None) -> None:
        super().__init__(username=username, role=Role.ADMIN, id=id)


class Member(BaseMember):
    def __init__(self, username: str, id: Optional[int] = None) -> None:
        super().__init__(username=username, role=Role.MEMBER, id=id)


class Maintainer(BaseMember):
    def __init__(self, username: str, id: Optional[int] = None) -> None:
        super().__init__(username=username, role=Role.MAINTAINER, id=id)


teamsconfig_t = Dict[str, Union[Set[Team], Dict[str, Union[Set[BaseMember], Policy[BaseMember], Policy[Team]]]]]


class TeamsConfig(GHConfModuleDef):
    applies_to_organization = True

    def __init__(self, config: Dict[str, Any]) -> None:
        self.config = config
        super().__init__()

    @staticmethod
    def apply_team_change(change: Change[Team], org: Organization) -> Change[Team]:
        if change.action not in [ChangeActions.ADD, ChangeActions.REMOVE]:
            print_warning("Unsupported change action for teams: %s" % change.action)
            return change.skipped()

        if change.action == ChangeActions.ADD and change.after is not None:
            to_create = change.after  # type: Team
            if not isinstance(to_create, Team):
                raise ErrorMessage("Create action without team to create")

            created = org.create_team(to_create.name, permission=to_create.default_permission,
                                      privacy=to_create.privacy)
            created.edit(created.name, description=to_create.description)
            to_create.id = created.id
            return change.success()
        elif change.action == ChangeActions.REMOVE and change.before is not None:
            try:
                print_debug("Retrieving team id %s for deletion" % highlight(str(change.before.id)))
                to_delete = org.get_team(change.before.id)  # type: GithubTeam
            except GithubException:
                # if the team is already gone... ok
                return change.success()

            try:
                print_debug("Deleting team id %s" % highlight(str(change.before.id)))
                to_delete.delete()
            except GithubException as e:
                print_error("Can't delete team id %s: %s" %
                            (highlight(str(change.before.id)), str(e)))
                return change.failure()
            change.before.id = None
        return change.success()

    @staticmethod
    def apply_subteam_change(change: Change[Team], org: Organization, parent: Team) -> Change[Team]:
        if change.action not in [ChangeActions.ADD, ChangeActions.REMOVE]:
            print_warning("Unsupported change action for subteams: %s" % change.action)
            return change.skipped()

        if change.action == ChangeActions.ADD and change.after is not None:
            child = org.get_team(change.after.id)  # type: GithubTeam
            child.edit(child.name, parent_team_id=parent.id)
            if child.parent.id == parent.id:
                return change.success()
            else:
                return change.failure()
        elif change.action == ChangeActions.REMOVE and change.before is not None:
            child = org.get_team(change.before.id)
            if child.delete():
                return change.success()
            else:
                return change.failure()
        return change.success()

    @staticmethod
    def apply_member_change(change: Change[BaseMember], org: Organization, team: Team) -> Change[BaseMember]:
        if change.action not in [ChangeActions.ADD, ChangeActions.REMOVE]:
            print_debug("Unsupported change action for team members: %s" % change.action)
            return change.skipped()

        from ghconf.github import get_github
        if change.action == ChangeActions.ADD and change.after is not None:
            ghteam = org.get_team(team.id)
            ghmember = get_github().get_user(change.after.username)
            membership = ghteam.add_membership(ghmember, role=change.after.role)
            if membership.state == "active":
                print_debug("Added member %s to team %s" % (change.after.username, team.name))
                return change.success()
            else:
                print_debug("Adding member %s to team %s failed with state %s" %
                            (change.after.username, team.name, membership.state))
                return change.failure()
        elif change.action == ChangeActions.REMOVE and change.before is not None:
            ghteam = org.get_team(team.id)
            ghmember = get_github().get_user(change.before.username)
            if ghteam.remove_membership(ghmember):
                return change.success()
            else:
                return change.failure()
        return change.success()

    @staticmethod
    def apply_member_removal(change: Change[str], org: Organization) -> Change[str]:
        if change.action != ChangeActions.REMOVE:
            print_debug("Unsupported change action for member removal: %s" % change.action)
            return change.skipped()

        from ghconf.github import get_github
        print_debug("Removing member %s from org" % change.before)
        ghmember = get_github().get_user(change.before)
        org.remove_from_members(ghmember)
        return change.success()

    @staticmethod
    def apply_admin_change(change: Change[Admin], org: Organization) -> Change[Admin]:
        if change.action not in [ChangeActions.ADD, ChangeActions.REMOVE]:
            print_warning("Unsupported change action for org admins: %s" % change.action)
            return change.skipped()

        from ghconf.github import get_github
        if change.action == ChangeActions.ADD and change.after is not None:
            try:
                user = get_github().get_user(change.after.username)
                org.add_to_members(user, role="admin")
            except GithubException as e:
                print_debug("Unable to add admin user %s: %s" % (change.after.username, str(e)))
                return change.failure()
        elif change.action == ChangeActions.REMOVE and change.before is not None:
            try:
                user = get_github().get_user(change.before.username)
                org.remove_from_members(user)
            except GithubException as e:
                print_debug("Unable to remove admin user %s: %s" % (change.before.username, str(e)))
                return change.failure()
        return change.success()

    @staticmethod
    def apply_attr_change(change: Change[str], org: Organization, team: Team, attr: str) -> Change[str]:
        if change.action not in [ChangeActions.REPLACE]:
            print_warning("Unsupported change action for team attributes: %s" % change.action)
            return change.skipped()

        ghteam = org.get_team(team.id)  # type: GithubTeam

        if getattr(ghteam, attr) == change.before:
            print_info("Setting {attr} from {before} to {after} on team {id}".format(
                attr=attr, before=change.before, after=change.after, id=team.id
            ))
            ghteam.edit(team.name, **{attr: change.after})
            return change.success()

        return change

    def walk_team(self, org: Organization, team: Team, teammap: Dict[str, Team]) -> List[ChangeSet]:
        """
        Walk the team tree and find differences between the current hierarchy and the planned hierarchy
        :param org:
        :param team:
        :param teammap:
        :return:
        """
        ret = []
        member_meta = ChangeMetadata(
            executor=self.apply_member_change,
            params=[org, team]
        )
        member_changes = team.member_policy.apply_to_set(
            meta=member_meta,
            current=teammap[team.name].members if team.name in teammap else set(),
            plan=team.members,
        )
        if member_changes:
            ret.append(ChangeSet(
                "{name}: Team {team}".format(name=__name__, team=team.name),
                member_changes,
            ))

        subteam_meta = ChangeMetadata(
            executor=self.apply_subteam_change,
            params=[org, team]
        )
        subteam_changes = team.team_policy.apply_to_set(
            meta=subteam_meta,
            current=teammap[team.name].subteams if team.name in teammap else set(),
            plan=team.subteams
        )
        if subteam_changes:
            ret.append(ChangeSet(
                "{name}: Team hierarchy {team}".format(name=__name__, team=team.name),
                subteam_changes
            ))
        for st in team.subteams:
            ret += self.walk_team(org, st, teammap)
        return ret

    def flatten_team_structure(self, toplevel: Set[Team]) -> Set[Team]:
        """
        Create a flat set of all teams in the team hierarchy
        """
        flat = toplevel  # type: Set[Team]
        for t in toplevel:
            if t.subteams:
                flat = flat.union(self.flatten_team_structure(t.subteams))
        return flat

    def flatten_member_structure(self, toplevel: Set[Team]) -> Set[BaseMember]:
        """
        Create a flat set of all members assigned to the org via teams
        """
        members = set()  # type: Set[BaseMember]
        for t in toplevel:
            members = members.union(t.get_all_members())
        return members

    def create_attr_change(self, org: Organization, attr: str, current: Team, plan: Team,
                           override_attr_name: Optional[str] = None) -> Union[None, Change[str]]:
        if getattr(current, attr) != getattr(plan, attr):
            return Change(
                meta=ChangeMetadata(
                    executor=self.apply_attr_change,
                    params=[org, current, override_attr_name if override_attr_name else attr]
                ),
                action=ChangeActions.REPLACE,
                before=getattr(current, attr),
                after=getattr(plan, attr),
                cosmetic_prefix="%s %s:" % (plan.name, attr),
            )
        else:
            return None

    def diff_team_attrs(self, org: Organization, current: Team, plan: Team) -> List[Change[str]]:
        attr_changes = []  # type: List[Change[str]]
        for attr, override in [("privacy", None), ("default_permission", "permission"),
                               ("description", None)]:  # type: str, Optional[str]
            change = self.create_attr_change(org, attr, current, plan, override)
            if change:
                attr_changes.append(change)
        return attr_changes

    def build_organization_changesets(self, org: Organization) -> List[ChangeSet]:
        admin_meta = ChangeMetadata(
            executor=self.apply_admin_change,
        )
        admins = set([Admin(username=m.login, id=m.id) for m in org.get_members(role=Role.ADMIN)])
        admin_changes = self.config['organization'].get('admin_policy', OVERWRITE).apply_to_set(
            meta=admin_meta, current=admins, plan=self.config['organization']['admins'])

        ret = [ChangeSet("{name}: Admins".format(name=__name__), admin_changes)]

        member_meta = ChangeMetadata(
            executor=self.apply_member_removal,
            params=[org],
        )
        current_members = set([member.login for member in list(org.get_members(role="all"))])
        planned_members = set([member.username for member in self.flatten_member_structure(self.config["teams"])])
        member_changes = self.config['organization'].get('member_policy', OVERWRITE).apply_to_set(
            meta=member_meta, current=current_members, plan=planned_members
        )
        # in this case we only keep removals, as member additions are handled by the team changes below
        member_changes = [change for change in member_changes if change.action == ChangeActions.REMOVE]
        ret += [
            ChangeSet("{name}: Members".format(name=__name__), member_changes)
        ]

        ext_existing = cache.lazy_get_or_store("orgteams_%s" % org.name,
                                               lambda: list(org.get_teams()))  # type: List[GithubTeam]
        teammap = {
            ext_team.name: Team.from_githubteam(ext_team) for ext_team in ext_existing
        }  # type: Dict[str, Team]

        # match IDs to the Teams so we move existing teams instead of deleting and recreating them
        for t in self.flatten_team_structure(self.config["teams"]):
            if t.name in teammap:
                t.id = teammap[t.name].id

        for ext_team in ext_existing:
            if ext_team.parent and ext_team.parent.name in teammap:
                teammap[ext_team.parent.name].subteams.add(teammap[ext_team.name])

        team_meta = ChangeMetadata(
            executor=self.apply_team_change,
            params=[org]
        )
        ret += [ChangeSet(
            source="{name}|{org}: Teams".format(name=__name__, org=org.name),
            changes=self.config["organization"].get("team_policy", EXTEND).apply_to_set(
                meta=team_meta, current=set(teammap.values()), plan=self.flatten_team_structure(self.config["teams"])),
        )]

        attr_changes = []  # type: List[Change[str]]
        for t in self.flatten_team_structure(self.config["teams"]):
            if t.name in teammap:
                changes = self.diff_team_attrs(org, teammap[t.name], t)
                if changes:
                    attr_changes += changes

        ret += [ChangeSet(
            source="{name}: attributes".format(name=__name__),
            changes=attr_changes
        )]

        for team in self.config["teams"]:
            ret += self.walk_team(org, team, teammap)

        return ret
