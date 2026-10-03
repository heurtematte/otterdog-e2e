// An organization variable visible to every repository (an org-level object: its name carries the run prefix).
// Inject it as a 'variables' fragment: otterdog-e2e inject --fragment variables=scenarios/fragments/org-variable.jsonnet
orgs.newOrgVariable('{{ P }}_INJECTED') {
  value: 'injected by otterdog-e2e',
  visibility: 'public',
}
