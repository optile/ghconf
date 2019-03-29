# -* encoding: utf-8 *-
from datetime import datetime, timedelta
from typing import List, Dict, Union, Set, Optional, TypeVar

from github.GithubObject import NotSet, _NotSetType
from github.RequiredPullRequestReviews import RequiredPullRequestReviews
from github.RequiredStatusChecks import RequiredStatusChecks
from github.CommitStatus import CommitStatus
from github.GithubException import GithubException
from github.Repository import Repository
from github.Organization import Organization
from github.BranchProtection import BranchProtection
from github.Branch import Branch

from ghconf.base import Change, ChangeMetadata, ChangeAction, ChangeActions
from ghconf.plumbing.repositories import repoproc_t
from ghconf.utils import print_debug, highlight, print_error, print_warning


def make_develop_default(org: Organization, repo: Repository, branches: Dict[str, Branch]) -> List[Change[str]]:
    def execute_develop_default(change: Change[str], repo: Repository) -> Change[str]:
        print_debug("[%s] Changing default branch to 'develop'" % highlight(repo.name))
        try:
            repo.edit(default_branch="develop")
        except GithubException:
            return change.failure()

        return change.success()

    if repo.default_branch != "develop" and "develop" in branches and not repo.archived:
        change = Change(
            meta=ChangeMetadata(
                executor=execute_develop_default,
                params=[repo],
            ),
            action=ChangeActions.REPLACE,
            before=repo.default_branch,
            after="develop",
            cosmetic_prefix="Default:"
        )
        return [change]
    return []


def __execute_master_default(change: Change[str], repo: Repository) -> Change[str]:
    print_debug("[%s] Enforcing master as the default branch" % highlight(repo.name))
    try:
        repo.edit(default_branch="master")
    except GithubException:
        return change.failure()

    return change.success()


def force_master_default(org: Organization, repo: Repository, branches: Dict[str, Branch]) -> List[Change[str]]:
    if repo.default_branch != 'master' and 'master' in branches and not repo.archived:
        change = Change(
            meta=ChangeMetadata(
                executor=__execute_master_default,
                params=[repo],
            ),
            action=ChangeActions.REPLACE,
            before=repo.default_branch,
            after="master",
            cosmetic_prefix="Default:"
        )
        return [change]
    return []


def force_master_default_if_no_develop(org: Organization, repo: Repository,
                                       branches: Dict[str, Branch]) -> List[Change[str]]:
    if repo.default_branch != 'develop' and repo.default_branch != 'master' and not repo.archived:
        if "develop" not in branches and "master" in branches:
            change = Change(
                meta=ChangeMetadata(
                    executor=__execute_master_default,
                    params=[repo],
                ),
                action=ChangeActions.REPLACE,
                before=repo.default_branch,
                after="master",
                cosmetic_prefix="Default:"
            )
            return [change]
        elif "develop" not in branches and "master" not in branches:
            print_debug("Repo %s has neither 'develop' or 'master'" % repo.name)
            return []
        else:
            return []
    return []


def get_pr_branch(repo: Repository, branches: Dict[str, Branch]) -> Union[Branch, None]:
    if repo.default_branch in branches:
        return branches[repo.default_branch]
    else:
        return None


def _set_dismiss_stale_approvals(branch: Branch, dismiss_approvals: bool = True) -> List[Change[str]]:
    def execute_dismiss_reviews(change: Change[str], branch: Branch,
                                required_reviews: Optional[RequiredPullRequestReviews],
                                dismiss_approvals: bool) -> Change[str]:
        try:
            if branch.protected and required_reviews:
                print_debug("Setting already protected branch %s to %s stale reviews" %
                            (highlight(branch.name), highlight("dismiss" if dismiss_approvals else "allow")))
                branch.edit_required_pull_request_reviews(dismiss_stale_reviews=dismiss_approvals)
            else:
                print_debug("Changing branch %s to %s stale reviews" %
                            (highlight(branch.name), highlight("dismiss" if dismiss_approvals else "allow")))
                safe_branch_edit_protection(branch, dismiss_stale_reviews=dismiss_approvals)
        except GithubException as e:
            print_error("Can't set review dismissal on branch %s to %s: %s" %
                        (highlight(branch.name), str(dismiss_approvals), str(e)))
            return change.failure()
        return change.success()

    change_needed = False
    rpr = None  # type: Optional[RequiredPullRequestReviews]

    if branch.protected:
        prot = branch.get_protection()
        rpr = prot.required_pull_request_reviews
        if rpr.dismiss_stale_reviews == dismiss_approvals:
            print_debug("Branch %s already %s stale reviews" %
                        (highlight(branch.name), highlight("dismisses" if dismiss_approvals else "allows")))
            change_needed = False
        else:
            change_needed = True
    else:
        change_needed = True

    if change_needed:
        change = Change(
            meta=ChangeMetadata(
                executor=execute_dismiss_reviews,
                params=[branch, rpr, dismiss_approvals]
            ),
            action=ChangeActions.REPLACE if branch.protected else ChangeActions.ADD,
            before="%s stale reviews" % ("Allow" if dismiss_approvals else "Dismiss"),
            after="%s stale reviews" % ("Dismiss" if dismiss_approvals else "Allow"),
            cosmetic_prefix="Protect branch<%s>" % branch.name
        )
        return [change]
    return []


def force_pr_branch_stale_review_dismissal(org: Organization, repo: Repository,
                                           branches: Dict[str, Branch]) -> List[Change[str]]:
    prb = get_pr_branch(repo, branches)
    if prb:
        return _set_dismiss_stale_approvals(prb, True)
    else:
        return []


def force_branch_stale_review_dismissal(branch_name: str) -> repoproc_t:
    def _force_branch_stale_review_dismissal(org: Organization, repo: Repository,
                                             branches: Dict[str, Branch]) -> List[Change[str]]:
        if branch_name in branches:
            return _set_dismiss_stale_approvals(branches[branch_name])
        else:
            print_warning("Requested to dismiss stale reviews on branch %s on repo %s, but the branch does not exist." %
                          (highlight(branch_name), highlight(repo.name)))
            return []
    return _force_branch_stale_review_dismissal


def _protect_branch(branch: Branch, required_review_count: int) -> List[Change[str]]:
    def execute_review_protection(change: Change[str], branch: Branch,
                                  existing_protection: Optional[BranchProtection], review_count: int) -> Change[str]:
        try:
            if branch.protected and existing_protection and existing_protection.required_pull_request_reviews:
                if review_count > 0:
                    print_debug("Replacing review protection on branch %s (%s reviews)" %
                                (highlight(branch.name), str(review_count)))
                    branch.edit_required_pull_request_reviews(required_approving_review_count=review_count)
                else:
                    print_debug("Removing review protection on branch: %s" % highlight(branch.name))
                    branch.remove_required_pull_request_reviews()
            elif review_count > 0:
                print_debug("Adding review protection on branch: %s (%s reviews)" %
                            (highlight(branch.name), str(review_count)))
                safe_branch_edit_protection(branch, required_approving_review_count=review_count)
        except GithubException as e:
            print_error("Can't set review protection on branch %s to %s: %s" %
                        (highlight(branch.name), str(review_count), str(e)))
            return change.failure()
        return change.success()

    change_needed = False
    prot = None
    current_reqcount = 0

    # The Github API will gladly return a required review count > 0 for a branch that had a required review
    # count previously, but it has now been turned off. So we need to correlate a bunch of information to find
    # out whether the branch actually requires reviews or not.
    if branch.protected:
        prot = branch.get_protection()
        if prot and prot.required_pull_request_reviews:
            rpr = prot.required_pull_request_reviews  # type: RequiredPullRequestReviews
            if rpr.required_approving_review_count == required_review_count:
                print_debug("Branch %s already requires %s reviews" %
                            (highlight(branch.name), highlight(str(required_review_count))))
                change_needed = False
            else:
                current_reqcount = rpr.required_approving_review_count
                change_needed = True
        else:
            if required_review_count == 0 and (prot is None or prot.required_pull_request_reviews is None):
                print_debug("Branch %s required no review and requested count is %s" %
                            (highlight(branch.name), highlight("zero")))
                change_needed = False
            else:
                change_needed = True
    else:
        change_needed = True

    if change_needed:
        change = Change(
            meta=ChangeMetadata(
                executor=execute_review_protection,
                params=[branch, prot, required_review_count]
            ),
            action=ChangeActions.REPLACE if branch.protected else ChangeActions.ADD,
            before="Require %s reviews" % current_reqcount if branch.protected else "No protection",
            after="Require %s reviews" % required_review_count,
            cosmetic_prefix="Protect branch<%s>:" % branch.name
        )
        return [change]
    return []


def protect_pr_branch_with_approvals(count: int = 1) -> repoproc_t:
    def _protect_pr_branch_with_approvals(org: Organization, repo: Repository,
                                          branches: Dict[str, Branch]) -> List[Change[str]]:
        prb = get_pr_branch(repo, branches)
        if prb:
            return _protect_branch(prb, count)
        else:
            return []
    return _protect_pr_branch_with_approvals


def protect_branch_with_approvals(branch_name: str, count: int = 1) -> repoproc_t:
    def _protect_branch_with_approvals(org: Organization, repo: Repository,
                                       branches: Dict[str, Branch]) -> List[Change[str]]:
        if branch_name in branches:
            return _protect_branch(branches[branch_name], count)
        else:
            print_warning("Requested to protect branch %s on repo %s, but the branch does not exist." %
                          (highlight(branch_name), highlight(repo.name)))
            return []
    return _protect_branch_with_approvals


GOT = TypeVar("GOT")
_GithubOptional = Union[GOT, _NotSetType]


def safe_branch_edit_protection(branch: Branch, strict: _GithubOptional[bool] = NotSet,
                                contexts: _GithubOptional[List[str]] = NotSet,
                                enforce_admins: _GithubOptional[bool] = NotSet,
                                dismissal_users: _GithubOptional[List[str]] = NotSet,
                                dismissal_teams: _GithubOptional[List[str]] = NotSet,
                                dismiss_stale_reviews: _GithubOptional[bool] = NotSet,
                                require_code_owner_reviews: _GithubOptional[bool] = NotSet,
                                required_approving_review_count: _GithubOptional[int] = NotSet,
                                user_push_restrictions: _GithubOptional[List[str]] = NotSet,
                                team_push_restrictions: _GithubOptional[List[str]] = NotSet) -> None:
    try:
        prot = branch.get_protection()
    except GithubException as e:
        prot = None

    rsc = prot.required_status_checks if prot else None  # type: RequiredStatusChecks
    rpr = prot.required_pull_request_reviews if prot else None # type: RequiredPullRequestReviews
    protupr = prot.get_user_push_restrictions() if prot else None
    if protupr is None:
        upr = NotSet
    else:
        upr = [u.login for u in protupr]
    prottpr = prot.get_team_push_restrictions() if prot else None
    if prottpr is None:
        tpr = NotSet
    else:
        tpr = [t.name for t in prottpr]

    kw = {
        'strict': strict if strict != NotSet else (rsc.strict if rsc else NotSet),
        'contexts': contexts if contexts != NotSet else (rsc.contexts if rsc else NotSet),
        'enforce_admins': enforce_admins if enforce_admins != NotSet else (prot.enforce_admins if prot else NotSet),
        'dismissal_users': dismissal_users if dismissal_users != NotSet else [],
        'dismissal_teams': dismissal_teams if dismissal_teams != NotSet else [],
        'dismiss_stale_reviews':
            dismiss_stale_reviews if dismiss_stale_reviews != NotSet else (
                rpr.dismiss_stale_reviews if rpr is not None else NotSet),
        'require_code_owner_reviews':
            require_code_owner_reviews if require_code_owner_reviews != NotSet else (
                rpr.require_code_owner_reviews if rpr is not None else NotSet),
        'required_approving_review_count':
            required_approving_review_count if required_approving_review_count != NotSet else (
                rpr.required_approving_review_count if rpr is not None else NotSet),
        'user_push_restrictions': user_push_restrictions if user_push_restrictions != NotSet else upr,
        'team_push_restrictions': team_push_restrictions if team_push_restrictions != NotSet else tpr,
    }
    branch.edit_protection(**kw)


def protect_pr_branch_with_tests_if_any_exist(org: Organization, repo: Repository,
                                              branches: Dict[str, Branch]) -> List[Change[str]]:
    def execute_test_protection(change: Change[str], branch: Branch, existing_checks: Set[str],
                                known_checks: Set[str]) -> Change[str]:
        print_debug("[%s] Changing status checks on branch '%s' to [%s]" %
                    (highlight(repo.name), highlight(branch.name), highlight(", ".join(list(known_checks)))))
        try:
            if existing_checks:
                branch.edit_required_status_checks(strict=True, contexts=list(known_checks))
            else:
                safe_branch_edit_protection(
                    branch,
                    strict=True,
                    contexts=list(known_checks),
                )
        except GithubException as e:
            print_error("Can't edit required status checks on repo %s branch %s: %s" %
                        (repo.name, branch.name, str(e)))
            return change.failure()
        return change.success()

    prb = get_pr_branch(repo, branches)
    if not prb:
        return []

    existing_checks = set()  # type: Set[str]
    try:
        rqs = prb.get_required_status_checks()
    except GithubException:
        # the repository has currently no status checks
        pass
    else:
        if len(rqs.contexts) > 0:
            # The repository already has some status checks, in that case we do nothing
            existing_checks = set(rqs.contexts)
            print_debug("Branch %s on repo %s already has status checks [%s]" %
                        (highlight(prb.name), highlight(repo.name), highlight(", ".join(existing_checks))))

    # the repository currently has no status checks, let's see if any came in within the last 7 days
    sevendaysago = datetime.now() - timedelta(days=7)
    known_checks = set()  # type: Set[str]
    for commit in repo.get_commits(prb.name, since=sevendaysago):
        for status in commit.get_statuses():  # type: CommitStatus
            known_checks.add(status.context)

    if known_checks and known_checks != existing_checks:
        # add all known checks as required checks
        print_debug('Adding checks [%s] to branch %s on repo %s' %
                    (highlight(", ".join(known_checks)), highlight(prb.name), highlight(repo.name)))
        return [Change(
            meta=ChangeMetadata(
                executor=execute_test_protection,
                params=[prb, existing_checks, known_checks]
            ),
            action=ChangeActions.REPLACE if existing_checks else ChangeActions.ADD,
            before="%s checks" % len(existing_checks) if existing_checks else "No checks",
            after="%s checks" % len(known_checks),
        )]
    return []


def remove_all_status_checks_on_pr_branch(org: Organization, repo: Repository,
                                          branches: Dict[str, Branch]) -> List[Change[str]]:
    def execute_remove_all_status_checks(change: Change[str], branch: Branch, existing_checks: Set[str]) -> Change[str]:
        print_debug("Removing all status checks from branch %s" % highlight(branch.name))
        try:
            if existing_checks:
                branch.remove_required_status_checks()
        except GithubException as e:
            print_error(str(e))
            return change.failure()
        else:
            return change.success()

    prb = get_pr_branch(repo, branches)
    if not prb:
        return []

    existing_checks = set()  # type: Set[str]
    try:
        rqs = prb.get_required_status_checks()
    except GithubException:
        # the repository has currently no status checks
        pass
    else:
        if len(rqs.contexts) > 0:
            existing_checks = set(rqs.contexts)
            return [Change(
                meta=ChangeMetadata(
                    executor=execute_remove_all_status_checks,
                    params=[prb, existing_checks]
                ),
                action=ChangeActions.REPLACE,
                before="%s checks" % len(existing_checks),
                after=None,
            )]
    return []


def set_repo_features(enable_wiki: bool = False, enable_issues: bool = False,
                      enable_projects: bool = False) -> repoproc_t:
    def _set_repo_features(org: Organization, repo: Repository, branches: Dict[str, Branch]) -> List[Change[str]]:
        def execute_set_repo_features(change: Change[str], repo: Repository,
                                      enable_wiki: Optional[bool] = None,
                                      enable_issues: Optional[bool] = None,
                                      enable_projects: Optional[bool] = None) -> Change[str]:
            if change.action == ChangeActions.REPLACE:
                print_debug("[%s] Setting features" % highlight(repo.name))
                kw = {
                    'has_wiki': NotSet if enable_wiki is None else enable_wiki,
                    'has_issues': NotSet if enable_issues is None else enable_issues,
                    'has_projects': NotSet if enable_projects is None else enable_projects
                }

                try:
                    repo.edit(**kw)
                except GithubException:
                    return change.failure()
            return change.success()

        if repo.archived:
            return []
        elif repo.has_issues or repo.has_wiki or repo.has_projects:
            psc = "X" if repo.has_projects else " "
            if not org.has_repository_projects:
                psc = "disabled"
            psp = "X" if enable_projects else " "
            if not org.has_repository_projects:
                psp = "disabled"
            before_state = "wiki[%s], issues[%s], projects[%s]" % (
                "X" if repo.has_wiki else " ",
                "X" if repo.has_issues else " ",
                psc
            )
            after_state = "wiki[%s], issues[%s], projects[%s]" % (
                "X" if enable_wiki else " ",
                "X" if enable_issues else " ",
                psp
            )
            print_debug("Enabling/disabling issue tracker, wiki and projects on %s" % (repo.name,))

            if ((enable_projects != repo.has_projects) and org.has_repository_projects) or \
                enable_issues != repo.has_issues or \
                    enable_wiki != repo.has_wiki:
                return [Change(
                    meta=ChangeMetadata(
                        executor=execute_set_repo_features,
                        params=[
                            repo,
                            enable_wiki,
                            enable_issues,
                            enable_projects if org.has_repository_projects else None
                        ],
                    ),
                    action=ChangeActions.REPLACE,
                    before=before_state,
                    after=after_state,
                    cosmetic_prefix="Repo features:"
                )]
        return []
    return _set_repo_features
