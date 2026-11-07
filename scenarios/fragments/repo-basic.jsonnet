// A public run repository with a description, topics and the wiki disabled; no library needed.
// Used by the ad-hoc injection recipes: otterdog-acceptance inject --fragment repositories=scenarios/fragments/repo-basic.jsonnet
orgs.newRepo('{{ p }}-basic') {
  description: 'otterdog e2e: basic repository',
  topics: ['otterdog-acceptance'],
  has_wiki: false,
}
