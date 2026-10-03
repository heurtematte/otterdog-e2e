local orgs = import 'vendor/template/otterdog-defaults.libsonnet';

orgs.newOrg('e2e-test-org', 'e2e-test-org') {
  settings+: {
    billing_email: "billing@example.org",
    blog: "https://example.org",
    default_branch_name: "trunk",
    description: "[otterdog-e2e] Dedicated otterdog e2e test organization",
    members_can_create_teams: true,
    members_can_delete_repositories: true,
    name: "E2E Test Org",
    packages_containers_internal: false,
    web_commit_signoff_required: false,
    workflows+: {
      default_workflow_permissions: "write",
    },
  },
}
