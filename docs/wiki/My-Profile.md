# My Profile

`/profile.html`. Your account, password, and two-factor authentication.

## Change password

Fields: current password, new password, repeat new password. On save the
server bumps your token epoch and revokes every existing session except
the one that just changed the password — you keep using the UI, anyone
else is signed out.

## Two-factor authentication

Status chip: **Not enabled** or enabled. **Set up 2FA** starts enrollment:

1. A QR code is shown — scan it with your authenticator app (Authy,
   Google Authenticator, Aegis, …).
2. Enter the 6-digit code to confirm.
3. **Backup codes** appear — store them somewhere safe. They are the only
   way in if you lose the phone.

## Verified

- Page loads with 2FA "Not enabled" for the admin account.
