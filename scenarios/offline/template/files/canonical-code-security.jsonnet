# O-CANON: the offline organization with a code security configuration delegating the push protection bypass,
# written exactly the way otterdog writes a configuration (GitHubOrganization.to_jsonnet): the list
# 'secret_scanning_delegated_bypass_reviewers' replaces the null default of the template (':'). canonical-diff drops
# the lines starting with '#' and ignores whitespace, trailing commas and the order of the lines, so its diff is empty
# on SUTs whose canonical form writes a list with a null default as a replacement (otterdog#916, 1.8.0); SUTs from
# otterdog#892 up to it write 'secret_scanning_delegated_bypass_reviewers+:' (null + array), older SUTs have no
# code security configurations at all.
local orgs = import '{{ import_path }}';

orgs.newOrg('{{ project }}', '{{ org }}') {
  code_security_configurations+: [
    orgs.newOrgCodeSecurityConfiguration('{{ p }}-bypass') {
      code_security: "enabled",
      secret_protection: "enabled",
      secret_scanning: "enabled",
      secret_scanning_delegated_bypass: "enabled",
      secret_scanning_delegated_bypass_reviewers: [
        "#OrganizationAdmin",
      ],
      secret_scanning_push_protection: "enabled",
    },
  ],
  settings+: {
    description: "otterdog-acceptance offline organization",
  },
}
