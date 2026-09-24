# Demo day — step by step

A runbook for showing DocuRoute on two or three devices over one network.
Follow it top to bottom. Setup and background are in `README.md`; this is only
what to do on the day.

Allow **15 minutes** before the audience arrives. Steps 1–7 take about five;
the rest is verifying on the real network, which is the part that catches
problems while there is still time to fix them.

---

## The day before

- [ ] **Test on the actual network you will present on.** This is the single
      most useful thing on this page. Guest and campus Wi-Fi frequently
      isolate clients from one another, which blocks everything here and
      cannot be detected from the laptop alone.
- [ ] Confirm the hotspot fallback works (step F below), so you are not
      configuring it for the first time under pressure.
- [ ] `git pull`, then run the whole of this checklist once.
- [ ] Charge every device. Bring the charger.

---

## 1. Free the memory

The assessment model needs about 700 MB resident. The laptop has 7.7 GB total
and is often down to ~1 GB free. If it has to page, a 14-second model load
becomes a minute.

- [ ] Close every browser window you are not presenting with — browsers are
      usually the largest consumer.
- [ ] Close Teams, Discord, Spotify, and any code editor you do not need.
- [ ] Check what is left:

```powershell
"{0:N1} GB free" -f ((Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory/1MB)
```

**Aim for 2 GB or more free.** Below 1.5 GB, close more.

---

## 2. Start the backend

From `Backend/`. The `0.0.0.0` matters — the default listens on loopback only,
so other devices cannot reach it.

```bash
py manage.py runserver 0.0.0.0:8000
```

- [ ] Leave this terminal open. Closing it stops the server.
- [ ] If Windows prompts about the firewall, tick **Private networks** and
      allow.

---

## 3. Start the frontend

From `frontend/`, in a second terminal. `host: true` is already in
`vite.config.js`, so no flag is needed.

```bash
npm run dev
```

- [ ] Allow the firewall prompt here too, on **Private networks**.
- [ ] **Write down the Network URL it prints**, e.g.

```
➜  Local:   http://localhost:5173/
➜  Network: http://192.168.11.181:5173/     ← this one
```

If it prints more than one Network line, you want the one matching the
Wi-Fi adapter. To confirm:

```powershell
Get-NetIPAddress -AddressFamily IPv4 |
  Where-Object { $_.InterfaceAlias -like "*Wi-Fi*" } |
  Select-Object IPAddress, InterfaceAlias
```

Addresses beginning `192.168.137.` are usually a Hyper-V or
internet-sharing adapter, not your Wi-Fi. Ignore those.

---

## 4. Pre-warm the model

The first check in a fresh server process spends about **14 seconds** loading
the encoder from disk. Every one after that takes **0.3 s**. That wait now
lands on a staff member part-way through submitting, so pay it before anyone
is watching.

**The easy way** — set the flag before starting the backend and it loads
itself on a background thread:

```bash
# Backend/, before runserver
$env:PREWARM_MODEL = "1"      # bash: export PREWARM_MODEL=1
py manage.py runserver 0.0.0.0:8000
```

Startup is not delayed: the server accepts requests immediately and the model
arrives about six seconds later.

- [ ] Set the flag, start the backend, and give it ten seconds.
- [ ] Confirm by running one check (below) — it should return in under a
      second.

**By hand**, if you forgot the flag or restarted without it:

- [ ] Sign in as staff, open a section, start an edit, and fill in a reason.
- [ ] Press **✨ Check with AI**. It will feel slow. That is the point.
- [ ] Press it again on a different edit and confirm it now returns almost
      instantly.

The model is cached per server process and shared by everyone, so warming it
once covers all devices. **Restarting the backend resets it** — if you restart
mid-demo, warm it again before showing a check.

---

## 5. Two roles, two browsers

Tokens live in `localStorage`, which is per browser profile. The same browser
cannot hold a staff session and an admin session at once — signing in as one
signs you out of the other.

- [ ] **Device A (you):** admin, in Chrome.
- [ ] **Device B:** staff, any browser.
- [ ] **Device C** (if used): a second staff account, so two submissions can
      arrive from different people.

If you are short of devices, one machine can run admin in Chrome and staff in
Firefox or an Edge profile. Incognito is not a reliable separator — use a
different browser.

---

## 6. Connect the other devices

- [ ] Confirm every device is on **the same Wi-Fi network** — not one on Wi-Fi
      and one on mobile data.
- [ ] On each device, open the Network URL from step 3:
      `http://<your-ip>:5173`
- [ ] Sign in.

**Only ever share the `:5173` address.** Nobody needs port 8000 — API calls
are relative and Vite forwards them.

---

## 7. Final check before the audience

- [ ] Each device loads the app and can sign in.
- [ ] Staff device: open a manual, open a section, see the content.
- [ ] From the staff device, as an Encoder (demo: `ACC_Juan`), open a section,
      choose **Propose changes**, change the text, give the reason and press
      **Run the check** — under a second once warm.
- [ ] Withdraw the test proposal as the Head (`ACC_Maria`) so it is not in
      the way - or use a document you will not show.

Demo accounts (from `seed_demo_org`), password `Office123!`: Accounting
Encoder `ACC_Juan` and Head `ACC_Maria`; concurring Heads `BUD_Jose` and
`CMO_Carlo`; a reader `BUD_Rosa`; the IMR `QMS_Ana`; the Document Custodian
`QMS_Pedro`.

---

## During the demo — a workable order

A change is proposed for a whole document; each changed section carries its
own AI check, made once and read by everyone after. Signatures stay on paper;
the system routes, records, generates the documents to sign, and stores the
signed scans.

1. **Draft** (`ACC_Juan`): open a document, choose **Propose changes**, edit a
   section, write the reason, **Run the check** - the concerns with clause and
   evidence, and an explanation of why they matter. Edit one word and the check
   clears: what everyone reads is always about the text submitted.
2. **Submit** (`ACC_Maria`, the Head): **Submit for concurrence**, with the
   password.
3. **Concurrence** (`BUD_Jose`, `CMO_Carlo`): each reads the change on
   **Awaiting my office** and concurs - or returns it with feedback, which
   sends it back as a new version that every office must agree to again.
4. **Locked**: the last concurrence freezes the text, numbers the request
   (`DCR-YYYY-NNN`) and generates the DCR, the draft copy and the annex.
5. **Signed copies** (`ACC_Juan`): upload the signed DCR and draft copy.
6. **IMR** (`QMS_Ana`): accept, or deny with a reason every office reads.
7. **Approving authority** (`ACC_Juan`): upload the DCR the approving
   authority signed.
8. **Custodian** (`QMS_Pedro`): record section 5 and **Make effective** - the
   text changes, the history names the DCR, and readers see the new revision
   and effectivity date. Or return the package for a defect in a signed copy.

Worth having ready to show deliberately:

- A **weakened obligation** ("shall" → "may") — rules and model agree, and the
  panel says so.
- A **throwaway reason** ("update") — refused at submission, which shows
  clause 6.3 being enforced rather than merely recorded.

---

## If a device cannot connect

Work through these in order. A is by far the most common.

### A. Firewall

The most likely cause, especially if the prompt appeared once and was
dismissed. From an **elevated** PowerShell:

```powershell
New-NetFirewallRule -DisplayName "DocuRoute demo" -Direction Inbound `
  -Protocol TCP -LocalPort 5173,8000 -Action Allow -Profile Private
```

Check it took:

```powershell
Get-NetFirewallRule -DisplayName "DocuRoute demo" | Select-Object Enabled, Profile
```

### B. Wi-Fi profile is Public

On a Public profile Windows blocks inbound connections **regardless of the
rule above**. Check and change:

```powershell
Get-NetConnectionProfile | Select-Object Name, NetworkCategory
Set-NetConnectionProfile -Name "<the Wi-Fi name>" -NetworkCategory Private
```

### C. Wrong address

- Using `localhost` or `127.0.0.1` on the *other* device — those mean that
  device. Use the `192.168.x.x` address.
- Using an address from a Hyper-V or internet-sharing adapter
  (`192.168.137.x`) instead of the Wi-Fi one.
- Missing the port. It is `:5173`, not bare.

### D. The backend is on loopback only

If the page loads but every action fails, the backend was started without
`0.0.0.0`. Confirm:

```powershell
Get-NetTCPConnection -State Listen -LocalPort 8000 | Select-Object LocalAddress
```

`0.0.0.0` is right. `127.0.0.1` means restart it as in step 2.

### E. Client isolation

If the firewall is open, the profile is Private, the address is right, and it
still fails — the network is isolating clients. Common on guest and campus
Wi-Fi, and **you cannot fix it from the laptop**. Go to F.

Quick test from another device: `ping 192.168.11.181`. No reply while both are
on the same Wi-Fi strongly suggests isolation.

### F. Hotspot fallback

Your own network, no isolation, works every time.

1. Windows **Settings → Network & Internet → Mobile hotspot → On**
   (or a phone's hotspot, with the laptop joined to it).
2. Connect every device, including the laptop, to that hotspot.
3. **The laptop's IP has changed.** Restart Vite (`Ctrl-C`, `npm run dev`) and
   read the new Network URL.
4. Re-share the new address.
5. The backend does not need restarting — `0.0.0.0` already covers the new
   interface.

Running the demo entirely on a phone hotspot is a legitimate choice, not a
last resort. If the venue Wi-Fi is unknown, start there.

---

## If something breaks mid-demo

**An assessment hangs.** It is loading the model — someone restarted the
backend, or step 4 was skipped. It will finish in about 15 seconds. Say what
it is doing; that is a more interesting answer than silence.

**Everything is slow.** Check free RAM (step 1). If the laptop is paging,
close a browser window.

**A device dropped off.** Re-check the Wi-Fi connection first; hotspots
sometimes drop idle clients. Reload the page — the session is in
`localStorage` and survives.

**The backend crashed.** Restart it (step 2), then **pre-warm again** (step 4)
before showing another assessment. Nothing is lost; everything is in the
database.

**Show the fallback instead.** If the model will not load at all, the rule
layer still answers on its own and the response says the model is unavailable.
A degraded but honest result is a reasonable thing to show, and explaining why
it degrades gracefully is a better answer than an apology.
