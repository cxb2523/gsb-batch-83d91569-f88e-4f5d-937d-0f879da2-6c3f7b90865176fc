# OpenWRT packages for UnTangled. Build the SPA first (npm run build), copy
# dist/ into ./files/www/untangled/, then build in an OpenWRT buildroot/SDK.
#
# Three packages from one source:
#   untangled       - minimal core: serve the UI + ubus/auth (HTTP). Tiny.
#   untangled-full  - core + Wi-Fi scan, firmware/backup, WoL, HTTPS by default.
#   untangled-mesh  - mesh backend (rpcd helper + dawn/umdns); payload in files-mesh/.
# Payload dirs: files/ (core), files-full/ (uci-defaults for -full), files-mesh/.
include $(TOPDIR)/rules.mk

PKG_NAME:=untangled
PKG_VERSION:=0.1.0
PKG_RELEASE:=1
PKG_LICENSE:=GPL-2.0-or-later
PKG_MAINTAINER:=Krish Paul <me@krishnendu.com>

include $(INCLUDE_DIR)/package.mk

define Package/untangled
  SECTION:=net
  CATEGORY:=Network
  SUBMENU:=Web Servers/Proxies
  TITLE:=UnTangled web interface (core)
  URL:=https://github.com/bidhata/untangled
  # Minimal: serve static files + /ubus, with session auth and file ops.
  DEPENDS:=+uhttpd +uhttpd-mod-ubus +rpcd +rpcd-mod-file +rpcd-mod-luci
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
  # Pulls the optional capabilities. HTTPS needs a TLS stack + self-signed cert
  # generator; depend on the VIRTUAL providers (libustream-ssl / px5g) so any
  # already-installed variant (mbedtls/openssl/wolfssl) satisfies them. Hard-
  # depending on the -mbedtls variants clashes on images that ship the openssl/
  # wolfssl ones (e.g. FriendlyWrt): both own /lib/libustream-ssl.so and
  # /usr/sbin/px5g. See https://github.com/bidhata/untangled/issues/2
  DEPENDS:=+untangled +rpcd-mod-iwinfo +rpcd-mod-rpcsys +rpcd-mod-luci +libustream-ssl +px5g +cgi-io +etherwake
  PKGARCH:=all
endef

define Package/untangled-full/description
  Meta-package (pulls in the core UI plus the extras below; the small package
  size is expected). UnTangled core plus Wi-Fi scan/association info, firmware
  upgrade (rpc-sys + cgi-io), Wake-on-LAN (etherwake), and HTTPS by default
  (self-signed cert via px5g; plain HTTP redirects to HTTPS).

  Optional feature screens install their backing package on demand (each
  degrades to an "install X" prompt when absent): QoS -> sqm-scripts,
  Dynamic DNS -> ddns-scripts, UPnP -> miniupnpd, Dual WAN -> mwan3,
  USB file sharing -> ksmbd (or samba4), media server -> minidlna,
  ad/threat blocking -> adblock/banip, usage history -> vnstat + nlbwmon.
  Mesh Wi-Fi -> the separate 'untangled-mesh' package.
endef

define Package/untangled-mesh
  SECTION:=net
  CATEGORY:=Network
  SUBMENU:=Web Servers/Proxies
  TITLE:=UnTangled Mesh Wi-Fi (backend)
  URL:=https://github.com/bidhata/untangled
  # Device-side helper for the Mesh Wi-Fi screen (which ships in the core UI and
  # degrades gracefully until this is installed). dawn = seamless 802.11r/k/v
  # roaming; umdns = mesh node discovery. For a WIRELESS 802.11s backhaul also
  # install a mesh-capable wpad (e.g. wpad-mesh-mbedtls); wired backhaul needs
  # nothing extra.
  DEPENDS:=+untangled +dawn +umdns
  PKGARCH:=all
endef

define Package/untangled-mesh/description
  Backend for UnTangled Mesh Wi-Fi: an rpcd helper (untangled.mesh) plus the
  roaming (dawn) and discovery (umdns) daemons. The mesh UI is part of the core
  package and appears as soon as this helper is present.
endef

# The SPA is prebuilt with Vite; nothing to compile in the buildroot.
define Build/Compile
endef

define Package/untangled/install
	$(INSTALL_DIR) $(1)/www/untangled
	$(CP) ./files/www/untangled/. $(1)/www/untangled/
	# Opt-in "default page": Administration can put this first in uhttpd's
	# index_page list so http://router/ opens UnTangled (LuCI untouched).
	$(INSTALL_DATA) ./files/www/untangled-home.html $(1)/www/untangled-home.html
	$(INSTALL_DIR) $(1)/usr/share/rpcd/acl.d
	$(INSTALL_DATA) ./files/usr/share/rpcd/acl.d/untangled.json $(1)/usr/share/rpcd/acl.d/untangled.json
	$(INSTALL_DIR) $(1)/etc/uci-defaults
	$(INSTALL_BIN) ./files/etc/uci-defaults/90-untangled $(1)/etc/uci-defaults/90-untangled
endef

# Meta-package: no files, just dependencies.
define Package/untangled-full/install
	$(INSTALL_DIR) $(1)/etc/uci-defaults
	$(INSTALL_BIN) ./files-full/etc/uci-defaults/91-untangled-https $(1)/etc/uci-defaults/91-untangled-https
endef

# Mesh backend: rpcd helper + first-boot defaults. (ACL methods are granted in
# the core untangled.json, so no extra ACL file here.)
define Package/untangled-mesh/install
	$(INSTALL_DIR) $(1)/usr/libexec/rpcd
	$(INSTALL_BIN) ./files-mesh/usr/libexec/rpcd/untangled.mesh $(1)/usr/libexec/rpcd/untangled.mesh
	$(INSTALL_DIR) $(1)/etc/uci-defaults
	$(INSTALL_BIN) ./files-mesh/etc/uci-defaults/92-untangled-mesh $(1)/etc/uci-defaults/92-untangled-mesh
endef

$(eval $(call BuildPackage,untangled))
$(eval $(call BuildPackage,untangled-full))
$(eval $(call BuildPackage,untangled-mesh))
