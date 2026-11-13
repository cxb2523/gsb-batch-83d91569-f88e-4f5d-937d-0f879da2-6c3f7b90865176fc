# UnTangled — Hardware & Roaming Support Matrix

A place to record what has actually been **tested on real hardware**, so field
reporters don't each burn a weekend rediscovering the same driver/client
breakage. UnTangled's config can look perfectly valid and still break roaming on
a specific radio-driver + client combo — especially **802.11r (Fast
Transition)**. If it isn't in a table below with a result, treat it as
**untested**, not "works".

Status legend:
- ✅ **OK** — tested on hardware, works as expected.
- ⚠️ **Partial** — works with caveats (see notes).
- ❌ **Broken** — known to fail; see the Known-broken section.
- ❔ **Untested** — no hardware report yet (the default for everything).

> Scope note (from the codebase): UnTangled targets OpenWRT **23.05** (stable,
> ipk) and **24.10 / latest** (+ snapshot apk), and has a field report on
> **25.12** (see §0). Mesh is **not** certified Multi-AP / prplMesh — it's
> "EasyMesh-like" (unified SSID + `dawn` roaming + wired backhaul today, 802.11s planned
> backhaul). Roaming and mesh rows below are still unvalidated on physical
> routers; each starts ❔ until someone files a result.

---

## 0. Device / UI support (basic bring-up)

"Does UnTangled install, serve, detect the board, and render on this device?"
This is a lighter bar than the roaming/mesh tables below — it does **not** imply
roaming or mesh works, only that the UI runs and reads the router correctly.

| Board / SoC | Model string (`system.board`) | OpenWRT release | UnTangled | Result | Notes |
|---|---|---|---|---|---|
| JioRouter AX6000 | `JioRouter AX6000 JIDU6101` | 25.12.6 `r33311-981c978eff` | 0.1 | ✅ | Reported by @spdixit. Network Map renders, board model + firmware detected, 24 clients listed, WAN online. Dual-band MediaTek MT798x (`mt76` / `mt798x-wmac`), 2.4 GHz + 5 GHz. Roaming/mesh **not** tested (see §1/§2). Earlier topbar showed stale demo values (`RT-AX88U`/`24.10`) — fixed: topbar now reads live `system.board`. |

---

## 1. Roaming features (802.11k/v/r) per radio driver

The feature we're most nervous about is **802.11r (FT)**. 802.11k (neighbor
reports) and 802.11v (BSS transition) give most of the roaming benefit with far
less client/driver breakage, so the honest recommendation is **k+v on, r
opt-in**.

| Board / SoC | Radio | Driver | OpenWRT release | 802.11k | 802.11v | 802.11r (FT) | Notes |
|---|---|---|---|---|---|---|---|
| JioRouter AX6000 (JIDU6101) | 2.4 GHz (phy0) | `mt76` (`mt798x-wmac`) | 25.12.6 | ❔ | ❔ | ❔ | MT798x SoC WiFi. Driver confirmed; roaming not tested. Also runs a STA uplink (`phy0-sta0` → `Airtel_sanj_7618`) with persistent `CTRL-EVENT-BEACON-LOSS` — a weak/unstable upstream link, not an UnTangled fault. |
| JioRouter AX6000 (JIDU6101) | 5 GHz (phy1) | `mt76` (`mt798x-wmac`) | 25.12.6 | ❔ | ❔ | ❔ | MT798x SoC WiFi; ch36, 160 MHz, AP (`Dixit-Home`). Driver confirmed; roaming not tested. |
| _example: TP-Link EAP615_ | 5 GHz | `ath11k` | 24.10 | ❔ | ❔ | ❔ | |
| | 2.4 GHz | `ath9k` | 23.05 | ❔ | ❔ | ❔ | |
| | 5 GHz | `ath10k` / `ath10k-ct` | 23.05 | ❔ | ❔ | ❔ | |
| | 2.4/5 GHz | `mt76` | 24.10 | ❔ | ❔ | ❔ | |
| | 6 GHz | `ath11k` | 24.10 | ❔ | ❔ | ❔ | |

Driver families to cover: `ath9k`, `ath10k` /
`ath10k-ct`, `ath11k`, `mt76`. These behave differently for FT — test each
separately rather than assuming one result carries over.

Fill one row per (board, radio/driver, release). FT especially is
**per-driver + per-client** — note the client side in the Notes column when a
combo fails (e.g. "iPhone 15 fine, Intel AX210 drops on FT").

---

## 2. Mesh (unified SSID + dawn roaming)

`untangled-mesh` ships the `untangled.mesh` rpcd helper. Phase-1 reality: single
router reports itself; multi-node discovery (umdns), 802.11s backhaul
(+`wpad-mesh`), and the dumb-AP bridging/DHCP-disable step are **deferred and
need ≥2 routers to validate**.

| Board / SoC | Driver | OpenWRT release | Backhaul | dawn roaming | Multi-node discovery | 802.11s | Notes |
|---|---|---|---|---|---|---|---|
| _example_ | `mt76` | 24.10 | wired | ❔ | ❔ | ❔ | needs 2 nodes |

Backhaul: `wired` only today (the plugin stores the value; nothing configures 802.11s yet). `802.11s` is planned and will need `wpad-mesh`.

---

## 3. Known-broken combos

Record confirmed failures here so they're greppable. One line each:

- _(none reported yet)_

<!-- Template:
- ❌ FT (802.11r) — <board> / <driver> <release>, client <device>: <symptom>.
  Workaround: <e.g. disable FT, k+v only>. Tracked: <issue link>.
-->

---

## 4. How to file a result

Test over `ROUTER=<ip> npm run dev` (live ubus — a bare container has no radios,
so container tests don't count for this matrix). For each board:

1. Note board/SoC, radio + **driver** (`iw dev` / `logread | grep -i <driver>`),
   and `cat /etc/openwrt_release`.
2. Enable the feature in UnTangled (Wireless roaming, or the Mesh plugin).
3. Roam a client between APs (or across a weak-signal boundary) and watch for
   drops / re-auth storms. Note the **client** device too.
4. Add a row above with ✅/⚠️/❌ and a one-line note. For ❌, add a Known-broken
   entry with the symptom and any workaround.

---

## 5. Jio JIDU model reference (JioRouter AX6000 family)

All Jio IDU (Indoor Unit) routers are branded **"JioRouter AX6000"** but fall
into **two distinct hardware families**. Source:
[wpfyorg/idu-unlock](https://github.com/wpfyorg/idu-unlock),
[Frozenxc/JioAF](https://github.com/Frozenxc/JioAF).

### MediaTek `6j01` family — MT7986A (Filogic 830)

All share: **MT7986A** (ARM Cortex-A53 dual-core), **512 MB RAM**, **256 MB
SPI-NAND** (UBI, dual-slot boot), **5× GbE + USB**, Wi-Fi 6 AX6000.
OpenWrt target: `mediatek/filogic`. Wi-Fi driver: **`mt76`** (`mt798x-wmac`).
**Official OpenWrt from 25.12.6** (needs [PR 25122](https://github.com/openwrt/openwrt/pull/25122)
SPI-NAND pinctrl fix, included in 25.12.6 images).

| Model | ODM | OpenWrt device identity | Notes |
|---|---|---|---|
| **JIDU6101** | Arcadyan | `jidu6101` (own identity) | First field report (this matrix, §0). |
| JIDU6201 | *(unknown)* | `jidu6j01` (shared) | Same hw as 6101, different ODM. |
| JIDU6401 | Sercomm | `jidu6j01` (shared) | UART photo available externally. |
| JIDU6601 | *(unknown)* | `jidu6j01` (shared) | |
| JIDU6701 | Skyworth | `jidu6j01` (shared) | |

Since all five are the same SoC/RAM/flash/radio, a result on any one should
carry to the others — **except** the device identity in `system.board` differs
(`jidu6101` vs `jidu6j01`), so the topbar will show the correct model per unit.

### Qualcomm `6j11` family — IPQ9574

| Model | ODM | Notes |
|---|---|---|
| JIDU6111 | *(unknown)* | |
| JIDU6411 | *(unknown)* | |
| JIDU6611 | Sercomm | |
| JIDU6811 | *(unknown)* | |
| JIDU6911 | *(unknown)* | |

SoC: **Qualcomm IPQ9574** (ARM Cortex-A73, quad-core). OpenWrt target:
`qualcommbe/ipq95xx`. Wi-Fi driver: **`ath11k`**. RAM/flash/port details not
publicly documented but likely similar to the 6j01 family.

**No official OpenWrt images** — only community builds from
[themayankraut](https://github.com/themayankraut/JIO-AX6000-6J11-OpenWRT-SSH).
UnTangled should work (it's arch-independent), but is completely untested on
this family. If a reporter files a result, this is a new driver family (`ath11k`
on IPQ95xx) worth a separate roaming-matrix row.

### NOT the same: JODU (Outdoor Unit)

Jio AirFiber also ships **JODU** models (JODU51641, 51642, 52041, 52140, 52240,
52540) — outdoor 5G/LTE fixed-wireless radios running OE/Yocto Linux, **not
OpenWrt**. UnTangled cannot target them. Don't confuse JIDU (indoor router)
with JODU (outdoor radio).
