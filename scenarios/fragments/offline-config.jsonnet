// A complete organization configuration: an offline step's 'config' or 'base_config' (otterdog-e2e inject --config
// or --base). It replaces the rendered two-layer file, so it imports the template itself (the only import a file may
// contain) and declares the organization; the Jinja variables import_path, project, org and plan come from the
// offline engine.
local orgs = import '{{ import_path }}';

orgs.newOrg('{{ project }}', '{{ org }}') {
  settings+: {
    plan: '{{ plan }}',
    description: '[otterdog-e2e] offline organization',
  },
  _repositories+: [
    orgs.newRepo('{{ p }}-from-config') {
      description: 'otterdog e2e: repository of a complete configuration',
    },
  ],
}
