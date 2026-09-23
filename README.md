# Cybreach-module2

Cybreach main integration repo — aggregates all pod work as git submodules.

## Pod directory mapping

| Pod | Responsibility | Repository directory |
| --- | --- | --- |
| Alpha | Rule Ingestion + Connector Framework | `VALIDATOR/` |
| Beta | Validation Engine + Outcome Classifier | `cybreach-module2-pod-beta/` |
| Gamma | OCSF Normalizer + Re-Validation Service | `cybreach_pod_gamma/` |
| Delta | Verdict Publisher + Frontend Dashboard + API Gateway | `verdict-platform/` |

## Adding your pod as a submodule

If you are a pod in-charge, add your repository here as a submodule under its mapped directory above:

```powershell
git submodule add <your-git-repo-url> <directory-name>
```

Example (Gamma):

```powershell
git submodule add https://github.com/Ayush-Sonwane/cybreach_pod_gamma cybreach_pod_gamma
```

This:

- clones your repo into the mapped directory,
- records the remote URL in `.gitmodules`,
- sets the working tree to your repo's default branch `HEAD`.

Commit the resulting `.gitmodules` and submodule entry, then push:

```powershell
git add .gitmodules <directory-name>
git commit -m "Add <pod> submodule"
git push
```

## Cloning this repo with submodules

```powershell
git clone --recurse-submodules <this-repo-url>
```

Already cloned? Run:

```powershell
git submodule update --init --recursive
```

## Updating a pod submodule

From the repo root, pull the latest of every pod and record the new pointers:

```powershell
git submodule update --remote
git add .
git commit -m "Update pod submodules"
git push
```