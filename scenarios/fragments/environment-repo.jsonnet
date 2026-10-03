// cli.environment: a public run repository with the deployment environment 'e2e-staging', restricted to selected
// branches. Needs the library 'e2e' (scenarios/lib/e2e.libsonnet).
// vars: wait_timer (minutes, a number), branch_policies (list of branch name patterns)
e2e.publicRepo('{{ p }}-env', 'otterdog e2e: deployment environment') {
  environments: [
    e2e.selectedBranchesEnvironment('e2e-staging', {{ branch_policies | tojson }}, wait_timer={{ wait_timer }}),
  ],
}
