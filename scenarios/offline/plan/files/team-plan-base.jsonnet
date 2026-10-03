// The -BASE side of O-LPLAN-READ-ONLY-KEYS/plan: the offline organization on the 'team' plan while the scenario
// renders the configuration on the 'free' plan (settings fragments and overlays may never set 'plan', a complete
// base_config file may). Everything else is the bare organization the offline engine renders.
local orgs = import '{{ import_path }}';

orgs.newOrg('{{ project }}', '{{ org }}') {
  settings+: {
    plan: 'team',
    description: '[otterdog-e2e] offline organization',
  },
}
