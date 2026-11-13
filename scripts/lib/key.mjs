import { readFile } from 'node:fs/promises';

export async function loadAPIKey(env = process.env) {
  if (env.FTSHARE_API_KEY?.trim()) return env.FTSHARE_API_KEY.trim();
  if (env.FTSHARE_API_KEY_FILE) return (await readFile(env.FTSHARE_API_KEY_FILE, 'utf8')).trim();
  return '';
}
