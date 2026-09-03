## Description

Brief description of the changes made.

## Type of Change

- [ ] Bug fix (non-breaking change which fixes an issue)
- [ ] New feature (non-breaking change which adds functionality)
- [ ] Breaking change (fix or feature that would cause existing functionality to not work as expected)
- [ ] Documentation update

## Testing

- [ ] I have added tests that prove my fix is effective or that my feature works
- [ ] New and existing tests pass locally with my changes
- [ ] I have tested the changes manually

## Quality Checks

- [ ] `pixi run format` — code is formatted
- [ ] `pixi run lint` — no ruff findings
- [ ] `pixi run typecheck` — no mypy errors
- [ ] `pixi run test-cov` — coverage stays at or above 90%
- [ ] `pixi run ci` — the full gate exits 0

## Django Considerations

- [ ] Any new model changes include a migration
- [ ] Migrations are reversible, or the irreversibility is called out below
- [ ] New settings are read from the environment and documented
- [ ] No secrets, keys, or `.env` contents are committed

## Checklist

- [ ] My commits follow the Conventional Commits spec (git-cliff builds the changelog from them)
- [ ] My code follows the style guidelines of this project
- [ ] I have performed a self-review of my own code
- [ ] I have commented my code, particularly in hard-to-understand areas
- [ ] I have made corresponding changes to the documentation
- [ ] My changes generate no new warnings

## Related Issues

Fixes #(issue number)
Related to #(issue number)

## Additional Context

Add any other context or screenshots about the pull request here.

---

### For Reviewers

Please ensure:

- [ ] Code quality meets project standards
- [ ] Tests are comprehensive and pass
- [ ] Documentation is updated if needed
- [ ] Breaking changes are clearly documented
- [ ] Security implications have been considered
- [ ] Migrations have been reviewed for data loss and lock duration
