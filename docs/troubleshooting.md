# Troubleshooting Guide

Common issues and solutions for BuildSite installations.

---

## 1. Action Fails with "Permission to repository denied" (HTTP 403)

### Cause
By default, some GitHub organizations or repositories restrict GitHub Actions workflow tokens to read-only permissions.

### Solution
1. Open your profile repository settings: **Settings** -> **Actions** -> **General**.
2. Scroll to **Workflow permissions**.
3. Select **"Read and write permissions"** and click **Save**.
4. Alternatively, explicitly define the permission block in your `.github/workflows/buildsite.yml`:
   ```yaml
   permissions:
     contents: write
   ```

---

## 2. Contribution Count Shows "0" or Missing Contributions

### Cause
GitHub's public API only reports public contributions unless private contributions are enabled in your user profile.

### Solution
1. Visit your public GitHub Profile page (`https://github.com/<your-username>`).
2. Above your contribution calendar, click **Contribution settings**.
3. Check the box for **"Private contributions"**.
4. Trigger the workflow manually from the **Actions** tab.

---

## 3. Scheduled Action Has Not Run Automatically

### Cause
GitHub Actions scheduled workflows (`cron`) run on a best-effort queue and may experience 15–45 minutes of scheduling jitter. In addition, GitHub automatically pauses scheduled workflows in repositories that have had no commit activity for 60 consecutive days.

### Solution
- To force an immediate update, go to the **Actions** tab, select **BuildSite**, and click **Run workflow**.
- The scheduled cron is configured by default to run daily at 06:00 UTC.

---

## 4. SVG Does Not Animate in Browser

### Cause
1. Your operating system or browser has **"Reduce Motion"** enabled. BuildSite strictly respects accessibility settings through `@media (prefers-reduced-motion: reduce)`.
2. You have configured `animation: none` in `buildsite.yml`.

### Solution
- If you desire animations, verify `animation: subtle` in `buildsite.yml` and ensure system motion preferences allow animation.
- Note that even without animations, the SVG is a fully rendered, high-resolution architectural image with complete HUD information.

---

## 5. Local CLI Error: "Layer not found"

### Solution
Ensure you run commands within the repository or that the `assets/` directory is present:
```bash
buildsite validate
```
If assets need to be regenerated:
```bash
python assets/builder.py
```
