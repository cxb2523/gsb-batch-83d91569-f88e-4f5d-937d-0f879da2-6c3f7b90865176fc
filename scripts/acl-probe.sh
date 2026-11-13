#!/bin/sh
# usage: scripts/acl-probe.sh <running-openwrt-container>
# Probes the rpcd ACL in openwrt/files/usr/share/rpcd/acl.d/untangled.json against a real
# OpenWRT rootfs (docker run -d --privileged -e CMD_ENV=/sbin/init ghcr.io/openwrt/rootfs:x86_64-23.05.5).
# Installs the ACL + two test logins (ut=admin, ro=readonly), then calls ubus with the session id,
# which is exactly how rpcd enforces file/uci grants. Expects every UI command to be allowed and
# every escape attempt to be denied.
C=$1; fail=0
docker cp /root/bhuci/openwrt/files/usr/share/rpcd/acl.d/untangled.json $C:/usr/share/rpcd/acl.d/untangled.json
docker exec $C sh -c '
uci -q delete rpcd.ut; uci -q delete rpcd.ro
uci set rpcd.ut=login; uci set rpcd.ut.username=ut; uci set rpcd.ut.password="\$p\$root"; uci add_list rpcd.ut.read=untangled; uci add_list rpcd.ut.write=untangled
uci set rpcd.ro=login; uci set rpcd.ro.username=ro; uci set rpcd.ro.password="\$p\$root"; uci add_list rpcd.ro.read=untangled-readonly; uci add_list rpcd.ro.write=untangled-readonly
uci commit rpcd; /etc/init.d/rpcd restart; sleep 1
mkdir -p /etc/crontabs /etc/openvpn; echo "# untangled acl test" > /etc/crontabs/root' >/dev/null
rpc() { # rpc <sid> <obj> <method> <json-params>  -> runs inside the container; rpcd enforces the file ACL from ubus_rpc_session
  p=$(printf %s "$4" | sed "s/^{/{\"ubus_rpc_session\":\"$1\",/")
  docker exec $C ubus call "$2" "$3" "$p" 2>&1
}
login() { docker exec $C ubus call session login "{\"username\":\"$1\",\"password\":\"\"}" | python3 -I -c 'import json,sys; print(json.load(sys.stdin)["ubus_rpc_session"])'; }
reason() { # normalise the ubus CLI's failure wording across versions
  r=$(printf %s "$1" | grep -o "Command failed: .*" | head -1); r=${r#Command failed: }
  case "$r" in *"("*")") r=${r##*(}; r=${r%)};; esac; printf %s "$r"
}
expect() { # expect <ALLOW|DENY> <label> <sid> <obj> <method> <params>
  out=$(rpc "$3" "$4" "$5" "$6"); r=$(reason "$out")
  case "$1:$r" in
    "ALLOW:"|"ALLOW:Not found"|"ALLOW:Unknown error") echo "  PASS  $1  $2 ${r:+($r)}";;
    "DENY:Access denied"|"DENY:Permission denied") echo "  PASS  $1  $2";;
    *) echo "  FAIL  $1  $2 -> ${r:-exit 0: $(printf %s "$out" | tr -d '\n' | cut -c1-120)}"; fail=1;;
  esac
}
has() { docker exec $C sh -c "command -v $1 >/dev/null 2>&1"; }
# ubus-level object/method gate (what uhttpd-mod-ubus enforces before forwarding)
expect_ubus() { # expect_ubus <ALLOW|DENY> <sid> <obj> <method>
  r=$(docker exec $C ubus call session access "{\"ubus_rpc_session\":\"$2\",\"scope\":\"ubus\",\"object\":\"$3\",\"function\":\"$4\"}" | python3 -I -c 'import json,sys; print(json.load(sys.stdin)["access"])')
  case "$1:$r" in ALLOW:True|DENY:False) echo "  PASS  $1  ubus-gate $3.$4";; *) echo "  FAIL  $1  ubus-gate $3.$4 = $r"; fail=1;; esac
}
SID=$(login ut); RO=$(login ro); echo "admin sid=$SID  readonly sid=$RO"
echo "[admin: things the UI does]"
expect ALLOW "exec /etc/init.d/cron restart"            $SID file exec '{"command":"/etc/init.d/cron","params":["restart"]}'
expect ALLOW "exec bare sysupgrade -b (PATH lookup)"     $SID file exec '{"command":"sysupgrade","params":["-b","/tmp/untangled-backup.tar.gz"]}'
expect ALLOW "exec rm -f backup"                         $SID file exec '{"command":"rm","params":["-f","/tmp/untangled-backup.tar.gz"]}'
expect ALLOW "exec ping plugin with host target"         $SID file exec '{"command":"ping","params":["-c","3","-w","5","127.0.0.1"]}'
expect ALLOW "exec etherwake (absent -> NOT_FOUND ok)"   $SID file exec '{"command":"etherwake","params":["-i","br-lan","00:11:22:33:44:55"]}'
expect ALLOW "read /etc/crontabs/root"                   $SID file read '{"path":"/etc/crontabs/root"}'
expect ALLOW "read /proc/mounts"                         $SID file read '{"path":"/proc/mounts"}'
expect ALLOW "write /etc/crontabs/root"                  $SID file write '{"path":"/etc/crontabs/root","data":"# untangled test\n","mode":384}'
expect ALLOW "write /etc/openvpn/x.ovpn"                 $SID file write '{"path":"/etc/openvpn/x.ovpn","data":"client\n","mode":384}'
expect ALLOW "uci get dhcp"                              $SID uci get '{"config":"dhcp"}'
expect ALLOW "uci get network"                           $SID uci get '{"config":"network"}'
echo "[admin: things an attacker would try]"
expect DENY  "exec /bin/sh -c id"                        $SID file exec '{"command":"/bin/sh","params":["-c","id"]}'
expect DENY  "exec sh via PATH"                          $SID file exec '{"command":"sh","params":["-c","id"]}'
expect DENY  "exec /etc/init.d/dropbear stop"            $SID file exec '{"command":"/etc/init.d/dropbear","params":["stop"]}'
expect DENY  "exec /sbin/sysupgrade -n /tmp/evil.bin"    $SID file exec '{"command":"sysupgrade","params":["-n","/tmp/evil.bin"]}'
expect DENY  "exec ping with flag-injection target"      $SID file exec '{"command":"ping","params":["-c","3","-w","5","-f"]}'
has apk  && expect DENY "exec apk add (not list)"        $SID file exec '{"command":"apk","params":["add","foo"]}'
has opkg && expect DENY "exec opkg install (not list)"    $SID file exec '{"command":"opkg","params":["install","foo"]}'
has apk  && expect ALLOW "exec apk list --installed"      $SID file exec '{"command":"apk","params":["list","--installed"]}'
has opkg && expect ALLOW "exec opkg list-installed"       $SID file exec '{"command":"opkg","params":["list-installed"]}'
expect DENY  "exec /etc/init.d/../../bin/sh traversal"   $SID file exec '{"command":"/etc/init.d/../../bin/sh","params":["-c","id"]}'
expect DENY  "read /etc/shadow"                          $SID file read '{"path":"/etc/shadow"}'
expect DENY  "read /etc/config/wireless via file"        $SID file read '{"path":"/etc/config/wireless"}'
expect DENY  "read traversal /etc/crontabs/../shadow"    $SID file read '{"path":"/etc/crontabs/../shadow"}'
expect DENY  "write /etc/passwd"                         $SID file write '{"path":"/etc/passwd","data":"x"}'
expect DENY  "write /etc/openvpn/../rc.local"            $SID file write '{"path":"/etc/openvpn/../rc.local","data":"x"}'
expect DENY  "write /etc/openvpn/x.sh (not .ovpn)"       $SID file write '{"path":"/etc/openvpn/x.sh","data":"x"}'
expect DENY  "file list /"                               $SID file list '{"path":"/"}'
expect DENY  "file remove /etc/rc.local (outside grants)" $SID file remove '{"path":"/etc/rc.local"}'
echo "[cgi-io scopes]"
for q in '"cgi-io","upload","write"' '"cgi-io","download","read"' '"file","/tmp/firmware.img","write"' '"file","/tmp/untangled-backup.tar.gz","read"'; do
  set -- $(echo $q | tr -d '"' | tr ',' ' ')
  r=$(docker exec $C ubus call session access "{\"ubus_rpc_session\":\"$SID\",\"scope\":\"$1\",\"object\":\"$2\",\"function\":\"$3\"}" | python3 -I -c 'import json,sys; print(json.load(sys.stdin)["access"])')
  [ "$r" = True ] && echo "  PASS  access $1 $2 $3 = $r" || { echo "  FAIL  access $1 $2 $3 = $r"; fail=1; }
done
echo "[ubus-level gates]"
expect_ubus ALLOW $SID hostapd.phy0-ap0 get_clients; expect_ubus ALLOW $RO hostapd.wlan1 get_clients; expect_ubus DENY $SID hostapd.phy0-ap0 del_client; expect_ubus ALLOW $SID file exec; expect_ubus ALLOW $SID rpc-sys upgrade_start; expect_ubus DENY $SID rpc-sys factory; expect_ubus DENY $SID file list; expect_ubus DENY $SID file remove
expect_ubus DENY $RO file exec; expect_ubus DENY $RO uci set; expect_ubus ALLOW $RO log read
echo "[readonly]"
expect ALLOW "ro: system board"                          $RO system board '{}'
expect ALLOW "ro: uci get system"                        $RO uci get '{"config":"system"}'
expect DENY  "ro: uci get wireless (Wi-Fi keys)"         $RO uci get '{"config":"wireless"}'
expect DENY  "ro: uci get network (PPPoE/WG keys)"       $RO uci get '{"config":"network"}'
expect DENY  "ro: file exec"                             $RO file exec '{"command":"/etc/init.d/cron","params":["restart"]}'
expect DENY  "ro: file read crontab"                     $RO file read '{"path":"/etc/crontabs/root"}'
expect DENY  "ro: uci set"                               $RO uci set '{"config":"system","section":"@system[0]","values":{"hostname":"x"}}'
docker exec $C rm -f /etc/openvpn/x.ovpn
[ $fail = 0 ] && echo "=== ALL ACL CHECKS PASSED on $C ===" || { echo "=== FAILURES on $C ==="; exit 1; }
