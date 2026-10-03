# O-CANON: the offline organization written exactly the way otterdog writes a configuration
# (GitHubOrganization.to_jsonnet: the template import bound to 'orgs', the organization, the settings that differ
# from the template defaults, then '_repositories+::' with the fields that differ from the default repository).
# canonical-diff drops the lines starting with '#' (this header) and compares the rest with the canonical form,
# ignoring whitespace, trailing commas and the order of the lines, so its diff is empty (BAT-12).
# vars: repo_description, the description of the repository (a jsonnet string without quotes or backslashes).
# The organization description has no bracketed word: the canonical form drops them (KB-050).
local orgs = import '{{ import_path }}';

orgs.newOrg('{{ project }}', '{{ org }}') {
  settings+: {
    description: "otterdog-e2e offline organization",
  },
  _repositories+:: [
    orgs.newRepo('{{ p }}-canon') {
      description: "{{ repo_description }}",
      has_wiki: false,
    },
  ],
}
