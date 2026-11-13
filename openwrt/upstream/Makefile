# UnTangled — DRAFT Makefile for submission to the official openwrt/packages feed.
#
# This is NOT the Makefile the project's own release CI uses (that one is
# ../Makefile, which assembles a local feed with files/ + a freshly built dist/).
# This draft follows openwrt/packages rules, which differ in two ways that matter:
#
#   1. NO NETWORK AT BUILD TIME. The OpenWRT buildbots are hermetic — you cannot
#      run `npm install` / `vite build` during package compile. So the SPA must
#      already be built. This Makefile therefore fetches a RELEASE TARBALL that
#      ALREADY CONTAINS the prebuilt `dist/` (and the files/ + files-mesh/ trees).
#
#   2. SOURCE IS A PINNED TARBALL, not a git checkout. PKG_SOURCE + PKG_HASH must
#      point at a stable, immutable artifact.
#
# ------------------------------------------------------------------------------
# WHAT YOU MUST DO BEFORE THIS BUILDS (one-time per release):
#
#   A tarball named untangled-$(PKG_VERSION).tar.gz must be attached to the
#   GitHub release and contain, at the top level:
#       dist/                         (output of `npm run build`)
#       files/                        (from openwrt/files/)
#       files-mesh/                   (from openwrt/files-mesh/)
#       LICENSE
#   i.e. a "product" tarball, not the plain source archive GitHub auto-generates
#   (that one has no dist/ and the build would serve nothing).
#
#   Build it in CI with something like:
#       npm ci && npm run build
#       mkdir -p pkg/untangled-$(VER)
#       cp -r dist LICENSE pkg/untangled-$(VER)/
#       cp -r openwrt/files openwrt/files-mesh pkg/untangled-$(VER)/
#       tar -C pkg -czf untangled-$(VER).tar.gz untangled-$(VER)
#   then attach untangled-$(VER).tar.gz to the release.
#
#   Get PKG_HASH with:  sha256sum untangled-$(VER).tar.gz
# ------------------------------------------------------------------------------

include $(TOPDIR)/rules.mk

PKG_NAME:=untangled
PKG_VERSION:=0.1.9
PKG_RELEASE:=1

PKG_SOURCE:=$(PKG_NAME)-$(PKG_VERSION).tar.gz
PKG_SOURCE_URL:=https://github.com/bidhata/untangled/releases/download/v$(PKG_VERSION)
# Replace with: sha256sum untangled-$(PKG_VERSION).tar.gz
PKG_HASH:=0000000000000000000000000000000000000000000000000000000000000000

PKG_MAINTAINER:=Krish Paul <me@krishnendu.com>
PKG_LICENSE:=GPL-2.0-or-later
PKG_LICENSE_FILES:=LICENSE

# The tarball unpacks to untangled-$(PKG_VERSION)/ (the default), so the stock
# PKG_BUILD_DIR is correct; no PKG_SOURCE_SUBDIR override needed.

include $(INCLUDE_DIR)/package.mk

define Package/untangled
  SECTION:=net
  CATEGORY:=Network
  SUBMENU:=Web Servers/Proxies
  TITLE:=UnTangled web interface (core)
  URL:=https://github.com/bidhata/untangled
  DEPENDS:=+uhttpd +uhttpd-mod-ubus +rpcd +rpcd-mod-file
  PKGARCH:=all
endef

define Package/untangled/description
  A modern, offline, dual-audience web UI for OpenWRT (an alternative to LuCI).
  Prebuilt static SPA served by uhttpd over ubus/rpcd. HTTP-only minimal install;
  add 'untangled-full' (or the individual packages) for HTTPS, Wi-Fi scan and
  firmware/backup.
endef

define Package/untangled-full
  SECTION:=net
  CATEGORY:=Network
  SUBMENU:=Web Servers/Proxies
  TITLE:=UnTangled web interface (full feature set)
  URL:=https://github.com/bidhata/untangled
  # Depend on the VIRTUAL TLS providers (libustream-ssl / px5g) so any installed
  # variant (mbedtls/openssl/wolfssl) satisfies the dependency. See issue #2.
  DEPENDS:=+untangled +rpcd-mod-iwinfo +rpcd-mod-rpcsys +rpcd-mod-luci +libustream-ssl +px5g +cgi-io +etherwake
  PKGARCH:=all
endef

define Package/untangled-full/description
  Meta-package (ships no files of its own — it just pulls in the core UI plus
  the extras below; the small package size is expected). UnTangled core plus
  Wi-Fi scan/association info, firmware upgrade (rpc-sys + cgi-io), Wake-on-LAN
  (etherwake), and TLS for HTTPS.

  Optional feature screens install their backing package on demand (each
  degrades to an "install X" prompt when absent): QoS -> sqm-scripts,
  Dynamic DNS -> ddns-scripts, UPnP -> miniupnpd-nftables, Dual WAN -> mwan3,
  USB file sharing -> ksmbd (or samba4), media server -> minidlna,
  ad/threat blocking -> adblock/banip, usage history -> vnstat + nlbwmon,
  Tailscale -> tailscale. Mesh Wi-Fi -> the separate 'untangled-mesh' package.
endef

define Package/untangled-mesh
  SECTION:=net
  CATEGORY:=Network
  SUBMENU:=Web Servers/Proxies
  TITLE:=UnTangled Mesh Wi-Fi (backend)
  URL:=https://github.com/bidhata/untangled
  DEPENDS:=+untangled +dawn +umdns
  PKGARCH:=all
endef

define Package/untangled-mesh/description
  Backend for UnTangled Mesh Wi-Fi: an rpcd helper (untangled.mesh) plus the
  roaming (dawn) and discovery (umdns) daemons. The mesh UI is part of the core
  package and appears as soon as this helper is present. For a wireless 802.11s
  backhaul also install a mesh-capable wpad (e.g. wpad-mesh-mbedtls); a wired
  backhaul needs nothing extra.
endef

# Prebuilt SPA — nothing to compile. (The tarball already contains dist/.)
define Build/Compile
endef

define Package/untangled/install
	$(INSTALL_DIR) $(1)/www/untangled
	$(CP) $(PKG_BUILD_DIR)/dist/. $(1)/www/untangled/
	$(INSTALL_DATA) $(PKG_BUILD_DIR)/files/www/untangled-home.html $(1)/www/untangled-home.html
	$(INSTALL_DIR) $(1)/usr/share/rpcd/acl.d
	$(INSTALL_DATA) $(PKG_BUILD_DIR)/files/usr/share/rpcd/acl.d/untangled.json $(1)/usr/share/rpcd/acl.d/untangled.json
	$(INSTALL_DIR) $(1)/etc/uci-defaults
	$(INSTALL_BIN) $(PKG_BUILD_DIR)/files/etc/uci-defaults/90-untangled $(1)/etc/uci-defaults/90-untangled
endef

# Meta-package: no files, just dependencies.
define Package/untangled-full/install
	true
endef

define Package/untangled-mesh/install
	$(INSTALL_DIR) $(1)/usr/libexec/rpcd
	$(INSTALL_BIN) $(PKG_BUILD_DIR)/files-mesh/usr/libexec/rpcd/untangled.mesh $(1)/usr/libexec/rpcd/untangled.mesh
	$(INSTALL_DIR) $(1)/etc/uci-defaults
	$(INSTALL_BIN) $(PKG_BUILD_DIR)/files-mesh/etc/uci-defaults/92-untangled-mesh $(1)/etc/uci-defaults/92-untangled-mesh
endef

$(eval $(call BuildPackage,untangled))
$(eval $(call BuildPackage,untangled-full))
$(eval $(call BuildPackage,untangled-mesh))
