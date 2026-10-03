// A public run repository protected by a default-branch ruleset: one approval, strict status checks.
// Needs the library 'e2e' (scenarios/lib/e2e.libsonnet).
e2e.publicRepo('{{ p }}-rules', 'otterdog e2e: repository ruleset') {
  rulesets: [
    e2e.defaultBranchRuleset('{{ p }}-main') {
      required_pull_request: orgs.newPullRequest() { required_approving_review_count: 1 },
      required_status_checks: e2e.statusChecks(['e2e-ci']),
    },
  ],
}
