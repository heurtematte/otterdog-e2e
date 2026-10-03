// otterdog-e2e scenario helpers (docs/writing-scenarios.md, "Injecting jsonnet from files").
//
// A scenario inlines this file with
//
//   libraries:
//     e2e: ../lib/e2e.libsonnet
//
// as 'local e2e = (<this file>);' right after the template import of the rendered organization configuration (the
// webapp evaluates ONE file: a library cannot be imported). The helpers use the template local 'orgs' (and could use
// libraries declared before this one). Plain jsonnet without Jinja: every name comes from the caller, written with
// the run prefix (the Jinja variables p, P and hook_base of the scenario), so cleanup and the janitor find every
// object the helpers create.
{
  // A public run repository with its description; everything else keeps the template defaults.
  publicRepo(name, description='otterdog e2e'):: orgs.newRepo(name) {
    description: description,
  },

  // A private run repository. The example template disables members_can_fork_private_repositories, so a private
  // repository needs allow_forking: false (validation error otherwise), and wikis on private repositories need a
  // paid plan (plan warning on Free). Never use it in the step that creates the repository: otterdog before
  // 1.7.0.dev14 cannot create a private repository without Code Security (#791); create it with publicRepo first.
  privateRepo(name, description='otterdog e2e'):: self.publicRepo(name, description) {
    private: true,
    allow_forking: false,
    has_wiki: false,
  },

  // A branch ruleset on the default branch without the template's pull request and status check rules (the
  // template's empty newStatusChecks() is suspected never to converge, KB-021): add the rules the scenario tests.
  defaultBranchRuleset(name):: orgs.newRepoRuleset(name) {
    include_refs+: ['~DEFAULT_BRANCH'],
    required_pull_request: null,
    required_status_checks: null,
  },

  // Required status checks of a ruleset; 'strict' is required since otterdog#790, and checks are written without
  // the 'any:' prefix (rulesets read them back without it, KB-020).
  statusChecks(checks, strict=true):: orgs.newStatusChecks() {
    strict: strict,
    status_checks: checks,
  },

  // A deployment environment restricted to the given branch name patterns.
  selectedBranchesEnvironment(name, branches, wait_timer=0):: orgs.newEnvironment(name) {
    wait_timer: wait_timer,
    deployment_branch_policy: 'selected',
    branch_policies: branches,
  },
}
