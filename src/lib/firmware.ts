// Firmware upgrade (sysupgrade). Uploads an image to /tmp via cgi-io, validates
// it with rpc-sys, then flashes it keeping (or wiping) settings. Needs
// rpcd-mod-rpcsys and the cgi-io package (/cgi-bin/cgi-upload).
import { call, getSession } from './ubus';
import { getBoard } from './net';

export interface FwInfo { model: string; firmware: string; }

export async function firmwareInfo(): Promise<FwInfo> {
  const b = await getBoard();
  return { model: b.model, firmware: b.firmware };
}

export interface UploadResult { size: number; checksum: string; sha256sum?: string }

/** Upload the image to /tmp/firmware.img through cgi-io. */
export async function uploadFirmware(file: File): Promise<UploadResult> {
  const fd = new FormData();
  fd.append('sessionid', getSession());
  fd.append('filename', '/tmp/firmware.img');
  fd.append('filemode', '600');
  fd.append('filedata', file, file.name);
  const res = await fetch('/cgi-bin/cgi-upload', { method: 'POST', body: fd });
  if (res.status === 404) throw new Error('cgi-io missing');
  if (!res.ok) throw new Error(`upload failed (HTTP ${res.status})`);
  return res.json();
}

export interface TestResult { code: number; stdout: string; stderr: string }

/** Ask the router whether the uploaded image is valid for this device. */
export async function testFirmware(): Promise<TestResult> {
  const r = await call<any>('rpc-sys', 'upgrade_test', {});
  return { code: Number(r?.code ?? 0), stdout: String(r?.stdout ?? ''), stderr: String(r?.stderr ?? '') };
}

/** Begin the flash. The device reboots; the HTTP connection will drop. */
export async function flashFirmware(keepSettings: boolean): Promise<void> {
  await call('rpc-sys', 'upgrade_start', { keep: keepSettings });
}

/** Remove a staged image if the user cancels. */
export async function cleanFirmware(): Promise<void> {
  await call('rpc-sys', 'upgrade_clean', {}).catch(() => {});
}

// ---- Config backup / restore ----------------------------------------------
// Backup: `sysupgrade -b` writes a tar.gz of /etc config; download via cgi-io.
// Restore: upload via cgi-io, apply with `sysupgrade -r`, then reboot.

const BACKUP_PATH = '/tmp/untangled-backup.tar.gz';

/** Create and download a config backup archive. */
export async function downloadBackup(): Promise<void> {
  const r = await call<any>('file', 'exec', { command: 'sysupgrade', params: ['-b', BACKUP_PATH] });
  if (r && typeof r.code === 'number' && r.code !== 0) {
    throw new Error(String(r.stderr || `sysupgrade exited ${r.code}`));
  }
  const fd = new FormData();
  fd.append('sessionid', getSession());
  fd.append('path', BACKUP_PATH);
  fd.append('filename', 'backup.tar.gz');
  const res = await fetch('/cgi-bin/cgi-download', { method: 'POST', body: fd });
  if (res.status === 404) throw new Error('cgi-io missing');
  if (!res.ok) throw new Error(`download failed (HTTP ${res.status})`);
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  const b = await getBoard().catch(() => ({ hostname: 'router' } as any));
  const stamp = new Date().toISOString().slice(0, 10);
  a.href = url;
  a.download = `backup-${b.hostname || 'router'}-${stamp}.tar.gz`;
  a.click();
  URL.revokeObjectURL(url);
  await call('file', 'exec', { command: 'rm', params: ['-f', BACKUP_PATH] }).catch(() => {});
}

/** Upload a backup archive and restore it, then reboot. */
export async function restoreBackup(file: File): Promise<void> {
  const path = '/tmp/untangled-restore.tar.gz';
  const fd = new FormData();
  fd.append('sessionid', getSession());
  fd.append('filename', path);
  fd.append('filemode', '600');
  fd.append('filedata', file, file.name);
  const up = await fetch('/cgi-bin/cgi-upload', { method: 'POST', body: fd });
  if (up.status === 404) throw new Error('cgi-io missing');
  if (!up.ok) throw new Error(`upload failed (HTTP ${up.status})`);
  const r = await call<any>('file', 'exec', { command: 'sysupgrade', params: ['-r', path] });
  if (r && typeof r.code === 'number' && r.code !== 0) {
    throw new Error(String(r.stderr || `restore exited ${r.code}`));
  }
  // Restore stages the files; a reboot applies them.
  await call('file', 'exec', { command: '/sbin/reboot' }).catch(() => {});
}
