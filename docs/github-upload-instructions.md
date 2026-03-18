# ForgeOS — GitHub & Forgejo Upload Instructions

Complete step-by-step guide for publishing the ForgeOS repository.

---

## Prerequisites (do these once on your local machine)

### 1. Install Git

**Windows:**
Download from https://git-scm.com/download/win — use all defaults during install.

**macOS:**
```bash
xcode-select --install
# or with Homebrew:
brew install git
```

**Linux (Ubuntu/Debian):**
```bash
sudo apt install git
```

Verify:
```bash
git --version
# Should output: git version 2.x.x
```

### 2. Configure Git identity (required for commits)

```bash
git config --global user.name  "Your Name"
git config --global user.email "you@example.com"
git config --global init.defaultBranch main
```

### 3. Generate an SSH key (recommended over HTTPS)

```bash
ssh-keygen -t ed25519 -C "you@example.com"
# Press Enter for all prompts (or set a passphrase)
```

Display the public key — you'll paste this into GitHub/Forgejo:
```bash
cat ~/.ssh/id_ed25519.pub
```

---

## Part 1: Upload to GitHub

### Step 1 — Create the GitHub repository

1. Go to **https://github.com** and sign in (or create an account)
2. Click the **+** in the top-right corner → **New repository**
3. Fill in the form:
   - **Repository name:** `forgeos`
   - **Description:** `Open-source NAS and home server platform for Ubuntu/Debian`
   - **Visibility:** Public (or Private if you prefer)
   - **⚠ Do NOT check** "Add a README file", "Add .gitignore", or "Choose a license"
     (we already have all of these — adding them here will cause a merge conflict)
4. Click **Create repository**
5. GitHub shows you a page with setup instructions. Leave this tab open.

### Step 2 — Add your SSH key to GitHub

1. Go to **https://github.com/settings/keys**
2. Click **New SSH key**
3. **Title:** `My computer` (or anything descriptive)
4. **Key type:** Authentication Key
5. **Key:** Paste the output of `cat ~/.ssh/id_ed25519.pub`
6. Click **Add SSH key**

Test the connection:
```bash
ssh -T git@github.com
# Expected: Hi YOUR_USERNAME! You've successfully authenticated...
```

### Step 3 — Prepare the local repository

Open a terminal and navigate to where you downloaded the ForgeOS files:

```bash
# If you downloaded a zip from Claude outputs, unzip it first
# Then navigate into the forgeos folder:
cd /path/to/forgeos

# Initialize git
git init

# Set the branch name to main
git branch -M main

# Stage all files
git add .

# Review what's being committed (important — make sure no secrets are listed)
git status

# Create the first commit
git commit -m "Initial release: ForgeOS v1.0

Complete NAS and home server platform for Ubuntu/Debian.

Includes:
- Modular installer (19 modules)
- ForgeOS desktop Web UI
- ForgeFileDB file-based database coordinator
- Storage: ForgeRAID (mdadm+btrfs), hot-swap, SMART, bcache
- File sharing: Samba, NFS v4, FTPS, WebDAV, FileBrowser
- Google Coral TPU support (single + dual, kernel 6.x compatible)
- GPU drivers: NVIDIA, AMD ROCm, Intel Arc
- Security: UFW, Fail2ban, CrowdSec, AppArmor, auditd
- Monitoring: Prometheus + Grafana + Alertmanager
- Backup: Restic AES-256 + Rclone crypt
- VPN: WireGuard + Netbird
- Mail: Postfix + Dovecot + Rspamd + SOGo
- Apps: OnlyOffice + MS Fonts + Immich
- Optional: HIPAA compliance, LDAP/OIDC SSO, MinIO S3"
```

### Step 4 — Connect to GitHub and push

Replace `YOUR_USERNAME` with your actual GitHub username:

```bash
# Add GitHub as the remote origin
git remote add origin git@github.com:YOUR_USERNAME/forgeos.git

# Push to GitHub
git push -u origin main
```

Expected output:
```
Enumerating objects: 45, done.
Counting objects: 100% (45/45), done.
...
Branch 'main' set up to track remote branch 'main' from 'origin'.
```

### Step 5 — Verify on GitHub

1. Go to `https://github.com/YOUR_USERNAME/forgeos`
2. You should see all files and the README rendered correctly
3. Go to the **Actions** tab — the CI pipeline will start automatically

### Step 6 — Configure repository settings (recommended)

1. Go to **Settings** (top of your repo page)

**General:**
- ✅ Enable **Issues**
- ✅ Enable **Projects**
- ✅ Enable **Wiki** (optional — for extended docs)
- Under "Pull Requests": enable "Allow squash merging", disable "Allow merge commits"

**Branches → Add branch protection rule** for `main`:
- ✅ Require a pull request before merging
- ✅ Require status checks: `ShellCheck`, `Python Syntax`, `Repo Structure`
- ✅ Do not allow bypassing the above settings

**Pages** (optional — publish docs as a website):
- Source: Deploy from a branch → `main` → `/docs`

### Step 7 — Add topics/tags (helps discoverability)

On the main repo page, click the gear icon next to "About":

Topics to add: `nas`, `home-server`, `self-hosted`, `ubuntu`, `debian`, `storage`, `samba`, `docker`, `linux`, `bash`

### Step 8 — Create a release

```bash
# Tag version 1.0
git tag -a v1.0.0 -m "ForgeOS v1.0.0 - Initial release"
git push origin v1.0.0
```

GitHub Actions will automatically build a release archive and attach it to the GitHub Releases page.

Or manually via the GitHub UI:
1. Click **Releases** → **Create a new release**
2. **Tag:** `v1.0.0`
3. **Title:** `ForgeOS v1.0.0`
4. Click **Generate release notes**
5. Click **Publish release**

---

## Part 2: Upload to Forgejo

Forgejo is a self-hosted Git platform (fork of Gitea). These instructions work for any Forgejo instance, including `codeberg.org` (the largest public Forgejo instance).

### Option A: Codeberg.org (public Forgejo hosting, free)

#### Step 1 — Create account
1. Go to **https://codeberg.org** and register
2. Verify your email

#### Step 2 — Add SSH key
1. Click your avatar → **Settings** → **SSH / GPG Keys**
2. Click **Add Key**
3. **Key Content:** paste `cat ~/.ssh/id_ed25519.pub`
4. Click **Add Key**

Test:
```bash
ssh -T git@codeberg.org
# Expected: Hi YOUR_USERNAME! You've successfully authenticated...
```

#### Step 3 — Create repository
1. Click **+** → **New Repository**
2. **Owner:** your username
3. **Repository Name:** `forgeos`
4. **Visibility:** Public
5. **⚠ Do NOT initialize** — leave README, .gitignore, license all unchecked
6. Click **Create Repository**

#### Step 4 — Push to Codeberg

If you already pushed to GitHub, add Codeberg as a second remote:

```bash
# Add Codeberg as a second remote
git remote add codeberg git@codeberg.org:YOUR_USERNAME/forgeos.git

# Push to Codeberg
git push -u codeberg main

# Push tags too
git push codeberg --tags
```

If Codeberg is your **only** target (no GitHub):
```bash
git remote add origin git@codeberg.org:YOUR_USERNAME/forgeos.git
git push -u origin main
git push origin --tags
```

---

### Option B: Self-hosted Forgejo instance

#### Step 1 — Install Forgejo on your server

On your ForgeOS server (or any server with Docker):

```bash
mkdir -p /srv/forgejo/{data,custom,backup,repositories,lfs}

docker run -d \
  --name forgejo \
  --restart always \
  -p 3000:3000 \
  -p 2222:22 \
  -v /srv/forgejo:/data \
  -e USER_UID=1000 \
  -e USER_GID=1000 \
  codeberg.org/forgejo/forgejo:7
```

Or with Docker Compose — create `/srv/forgejo/docker-compose.yml`:

```yaml
version: "3.8"
services:
  forgejo:
    image: codeberg.org/forgejo/forgejo:7
    container_name: forgejo
    restart: unless-stopped
    ports:
      - "3000:3000"
      - "2222:22"
    volumes:
      - /srv/forgejo:/data
    environment:
      - USER_UID=1000
      - USER_GID=1000
      - FORGEJO__database__DB_TYPE=sqlite3
      - FORGEJO__server__DOMAIN=git.your-domain.com
      - FORGEJO__server__ROOT_URL=https://git.your-domain.com
      - FORGEJO__server__SSH_DOMAIN=git.your-domain.com
      - FORGEJO__server__SSH_PORT=2222
```

```bash
docker compose up -d
```

#### Step 2 — Initial Forgejo setup

1. Open `http://your-server:3000` in a browser
2. Complete the install wizard:
   - Database: SQLite (simplest) or PostgreSQL
   - Site title: `ForgeOS Git`
   - Repository root: `/data/repositories`
   - Admin username/password: set a strong password
3. Click **Install Forgejo**

#### Step 3 — Add nginx proxy (optional but recommended)

```bash
# Using the ForgeOS nginx manager:
forgeos-nginx add-vhost forgejo git.your-domain.com 3000 acme none no
```

Or manually add to `/etc/nginx/forgeos.d/forgejo.conf`:

```nginx
server {
    listen 443 ssl http2;
    server_name git.your-domain.com;
    ssl_certificate     /etc/letsencrypt/live/your-domain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/your-domain.com/privkey.pem;
    client_max_body_size 512m;
    location / {
        proxy_pass http://127.0.0.1:3000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

#### Step 4 — Create repository in Forgejo

1. Log in to your Forgejo instance
2. Click **+** → **New Repository**
3. **Repository Name:** `forgeos`
4. **Visibility:** Public
5. **Leave all "Initialize" checkboxes unchecked**
6. Click **Create Repository**

#### Step 5 — Add SSH key to Forgejo

1. Click your avatar → **Settings** → **SSH / GPG Keys**
2. Click **Add Key**
3. Paste `cat ~/.ssh/id_ed25519.pub`
4. Click **Add Key**

Test (replace port 2222 if you used a different SSH port):
```bash
ssh -T -p 2222 git@git.your-domain.com
# Expected: Hi YOUR_USERNAME! You've successfully authenticated...
```

#### Step 6 — Push to self-hosted Forgejo

```bash
# If using SSH on non-standard port 2222:
git remote add forgejo ssh://git@git.your-domain.com:2222/YOUR_USERNAME/forgeos.git

# If using standard port 22:
git remote add forgejo git@git.your-domain.com:YOUR_USERNAME/forgeos.git

# Push
git push -u forgejo main
git push forgejo --tags
```

---

## Part 3: Mirror to both simultaneously (optional)

Push to GitHub AND Forgejo/Codeberg with one command:

```bash
# Add both remotes (if not already done)
git remote add github   git@github.com:YOUR_USERNAME/forgeos.git
git remote add codeberg git@codeberg.org:YOUR_USERNAME/forgeos.git

# Create an "all" remote that pushes to both
git remote add all git@github.com:YOUR_USERNAME/forgeos.git
git remote set-url --add --push all git@github.com:YOUR_USERNAME/forgeos.git
git remote set-url --add --push all git@codeberg.org:YOUR_USERNAME/forgeos.git

# Now push to both with one command:
git push all main
git push all --tags
```

Verify remotes:
```bash
git remote -v
# all      git@github.com:YOUR_USERNAME/forgeos.git (fetch)
# all      git@github.com:YOUR_USERNAME/forgeos.git (push)
# all      git@codeberg.org:YOUR_USERNAME/forgeos.git (push)
```

---

## Part 4: Ongoing workflow

### Making changes after initial upload

```bash
# Edit files as needed, then:
git add .
git status                    # review what changed
git commit -m "describe your change"
git push                      # pushes to whichever remote is 'origin'
# or:
git push all                  # pushes to GitHub + Forgejo simultaneously
```

### Releasing a new version

```bash
# After committing all changes:
git tag -a v1.1.0 -m "ForgeOS v1.1.0 - description of changes"
git push origin main
git push origin v1.1.0
# or for both:
git push all main
git push all v1.1.0
```

### Accepting contributions (pull requests)

On GitHub/Codeberg:
1. Contributors fork the repo and open Pull Requests
2. Your CI runs automatically on each PR
3. Review, approve, and merge via the web UI

On self-hosted Forgejo, same workflow applies.

---

## Quick Reference: Common Git Commands

```bash
git status              # What's changed?
git diff                # See exact changes
git add .               # Stage all changes
git add path/to/file    # Stage one file
git commit -m "msg"     # Commit staged changes
git push                # Upload commits
git pull                # Download latest
git log --oneline       # Recent commit history
git tag                 # List tags
git branch -a           # List branches
```

---

## Troubleshooting

**"Permission denied (publickey)"**
```bash
ssh-add ~/.ssh/id_ed25519      # Add key to SSH agent
ssh -T git@github.com          # Test connection
```

**"remote: Repository not found"**
- Double-check the remote URL: `git remote -v`
- Verify the repository exists on GitHub/Forgejo
- Make sure your username is correct in the URL

**"error: failed to push some refs"**
```bash
git pull --rebase origin main   # Sync with remote first
git push
```

**"refusing to merge unrelated histories"**
This happens if you initialized the remote with a README. Fix:
```bash
git pull origin main --allow-unrelated-histories
git push origin main
```
(This is why the instructions say to NOT initialize the repo on GitHub/Forgejo.)
