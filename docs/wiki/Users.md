# Users

`/users.html`. Accounts and 2FA policy.

## Require 2FA for new accounts

When on, every new user must enroll an authenticator from the
[My Profile](My-Profile) page before their first session is considered
complete.

## User list

Columns: USER, ROLE, 2FA, BACKUP CODES, and row actions (shield, lock,
reset, trash) shown at the right:
- **shield** — reset the user's 2FA enrollment.
- **lock** — lock/unlock the account.
- **reset** — reset the user's password.
- **trash** — delete the user (admin only, cannot delete yourself).

The last administrator cannot be deleted or demoted; the API enforces this.

**Add user** (top right) creates an account: username, password, role.

## My profile

The **My profile** button opens your own account page.

## Verified

- Two users exist: `admin (you)` role Administrator, `bob` role User, both
  with 2FA `Off`.
- Non-admin role cannot delete the last admin — enforced server-side.
