ghconf
======

This tool applies common GitHub configuration to a whole organization. It
currently supports Github teams and Github organizations (currently requires
an `unreleased version of PyGithub <pygithubpr_>`__).

* The configuration for this tool is passed as a Python module in its
  parameters.
* The config module must have a variable ``entry_point`` that is either a
  class, a list of classes, an instance or a list of instances of subclasses of
  ``GHConfModuleDef``.
* GHConf provides two configurable implementations of ``GHConfModuleDef``
  which should cover most use-cases. ``RepositoriesConfig`` for setting up
  your company's policies on all repositories and ``TeamsConfig`` to set up
  your organization's team structure and manage members via a declarative DSL.

GHConf only supports Python 3 and provides typing for validating all
configuration.


Usage
-----

.. code::

    usage: main.py [-h] [-o ORG] [-r REPOS] [-re REPOREGEXES]
                   [--no-repo-changes] [--no-org-changes]
                   [--github-token GITHUB_TOKEN] --module MODULES [--debug]
                   [--list-unconfigured-repos] [-v] [--no-color]
                   [--no-progressbar] [--plan] [--execute]

    ghconf is a tool that parses declarative configuration files in a Python
    DSL and then runs Python modules against a preconfigured PyGithub instance.
    This allows us to apply common GitHub configuration through GitHub's v3
    REST API to all repositories that are part of our organization.

    optional arguments:
      -h, --help            show this help message and exit
      -o ORG, --organization ORG
                            The GitHub organization to run against. The GitHub
                            API token must have write access to this
                            organization.
      -r REPOS, --repo REPOS
                            Specify one or more repositories to run the
                            configuration against. (Optional. If not specified,
                            changes will be made to all repos in the org as
                            modules see fit.)
      -re REPOREGEXES, --repo-regex REPOREGEXES
                            Specify one or more regular expressions to match
                            repositories to run the configuration against.
                            (Optional. If not specified, changes will be made
                            to all repos in the org as modules see fit.)
      --no-repo-changes     When set, ghconf will only execute org level
                            changes.
      --no-org-changes      When set, ghconf will not execute org level
                            changes.
      --github-token GITHUB_TOKEN
                            A GitHub API token for the user specified through
                            '--github-user' to use for accessing the GitHub
                            API.
                            (Envvar: GITHUB_TOKEN)
      --module MODULES      Specify Python modules as configuration that will
                            be imported by ghconf.
      --debug               Enable debug output about API interactions.
      --list-unconfigured-repos
                            List the names of all repositories that remain
                            untouched with the current configuration
      -v, --verbose         Verbose output. Include informational output, like
                            objects that don't change.
      --no-color            Don't output ANSI colors
      --no-progressbar      Skip the progress bar
      --plan                Evaluate all changes and show what the tool would
                            change with the current configuration.
      --execute             Execute any detected changes without asking first.
                            If this is not set, ghconf will ask for permission
                            before executing any changes.

Example
-------

.. code:: shell

    export GITHUB_TOKEN="your user access token"
    git clone ssh://git@github.com/optile/ghconf
    git clone -b optile-head ssh://git@github.com/optile/PyGithub
    # to run optile's config (it's a private repo)
    git clone ssh://git@github.com/optile/ghconf-optile
    virtualenv -p python3 ghconf
    ghconf/bin/pip install PyGithub/ -e ghconf/ -e ghconf-optile/
    ghconf/bin/python -m ghconf.main -o optile --module optile --plan


Policies
--------

GHConf's default implementations calculate differences between the provided
configuration module and the current state of your organization's Github relies
on ``Policy`` implementations. GHConf provides two policies ``EXTEND`` (leave
differences between the configuration and the current state intact) and
``OVERWRITE`` (enforce the configuration).


Team Configuration
------------------

.. code:: python

    from ghconf.plumbing.teams import teamsconfig_t
    from ghconf.primitives import OVERWRITE, EXTEND
    from ghconf.plumbing.teams import Admin, Team, Maintainer, Member, TeamsConfig

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
                            Maintainer("ghconf-test2"),
                            Member("ghconf-test3"),
                        }
                    ),
                }
            ),
        }
    }  # type: teamsconfig_t

    GhConfTestApplyTeams = TeamsConfig(config)


Repository Configuration
------------------------

.. code:: python

    from ghconf.plumbing.repositories import repoconfig_t
    from ghconf.primitives import OVERWRITE, EXTEND
    from ghconf.plumbing.repositories import common_procs, RepositoriesConfig

    #
    config = {
        re.compile(r'^test1[_\-]'): {
            'access': {
                'policy': OVERWRITE,
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
                common_procs.force_pr_branch_stale_review_dismissal,
                common_procs.disable_unnecessary_repo_features,
                common_procs.force_master_default_if_no_develop,
                common_procs.make_develop_default,
                common_procs.protect_pr_branch_with_tests_if_any_exist,
            ],
        },
    }  # type: repoconfig_t

    GhConfTestRepoApply = RepositoriesConfig(config)


PEP484 Typing
-------------

This code base has PEP484 annotations that you should reference when either
writing your own configuration or when implementing your own repository
configuration functions or even your own configuration providers.

In particular, please reference the following types if you want to write your
own configuration modules or repository configurators:

* ``ghconf.base.Change[CT]`` and ``ghconf.base.ChangeSet`` are how your code
  must return changes that it intends to make.
* ``ghconf.base.GHConfModuleDef`` is the baseclass for configuration modules.
  Ghconf includes two default implementations for team configuration and
  repository configuration.

Most use cases of this tool can properly be covered by the default team and
respository configurators in ``ghconf.plumbing.teams`` and
``ghconf.plumbing.repositories`` respectively. In which case the following type
definitions will be helpful for writing code:

* ``repoproc_t`` is the type of a function called on a repository
  for finding executing changes.
* ``repoconfig_t`` describes a repository configuration dict
  which maps regular expressions to actions to take on a repository.
* ``teamsconfig_t`` describes configuration for setting up
  teams.


.. _pygithubpr: https://github.com/PyGithub/PyGithub/pull/996
