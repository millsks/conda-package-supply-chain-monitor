"""Authorization: the claims contract and the claims-to-Django mapping.

Charter: AD-10 (the identity key is the IdP subject, never the email or the
username), AD-11 (the identity key is read from the claim the claims contract
designates), AD-12 (a token lacking the configured group claim is rejected;
`is_staff` and `is_superuser` each come from their own designated group).

This module is a package marker and deliberately re-exports nothing. Later
stories add `claims.py`, `mapper.py`, `jwks.py`, `authentication.py` and
`adapters.py` beside it, each imported from its own module so that the import
surface names the concern rather than the package.
"""
