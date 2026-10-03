// An overlay (a step's 'overlay', or otterdog-e2e inject --overlay): an object mixin applied after both layers of
// the rendered configuration, so it can rewrite what the fragments and the baseline declared. This one adds the
// topic 'e2e-overlay' to every repository of the run; repositories without the run prefix (the baseline ones) are
// left as they are.
{
  _repositories: [
    if std.startsWith(repo.name, '{{ p }}-') then repo { topics+: ['e2e-overlay'] } else repo
    for repo in super._repositories
  ],
}
