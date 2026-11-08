# O-CANON: the offline organization with a multi_select custom property, written exactly the way otterdog writes a
# configuration (GitHubOrganization.to_jsonnet): the list 'default_value' replaces the null default of the template
# (':'), the list 'allowed_values' extends its empty default ('+:'). canonical-diff drops the lines starting with '#'
# and ignores whitespace, trailing commas and the order of the lines, so its diff is empty on SUTs whose canonical
# form writes a list with a null default as a replacement (otterdog#916, 1.8.0); older SUTs write 'default_value+:',
# which jsonnet cannot evaluate (null + array).
local orgs = import '{{ import_path }}';

orgs.newOrg('{{ project }}', '{{ org }}') {
  settings+: {
    custom_properties+: [
      orgs.newCustomProperty('{{ p }}-langs') {
        allowed_values+: [
          "java",
          "python",
        ],
        default_value: [
          "java",
        ],
        required: true,
        value_type: "multi_select",
      },
    ],
    description: "otterdog-acceptance offline organization",
  },
}
