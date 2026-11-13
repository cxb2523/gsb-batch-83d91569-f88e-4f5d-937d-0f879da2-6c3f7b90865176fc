import { describe, it, expect } from 'vitest';
import { translateLocalhostForContainer } from '../src/docker.js';

describe('translateLocalhostForContainer', () => {
  // The reason this helper exists at all: when the runner runs on the host
  // (typical local dev) and spawns an actor container, `localhost` inside the
  // actor resolves to the actor itself. Docker Desktop on macOS exposes
  // `host.docker.internal` for the host. Linux has no such default.

  it('rewrites localhost to host.docker.internal on darwin', () => {
    expect(translateLocalhostForContainer('http://localhost:3000', 'darwin')).toBe(
      'http://host.docker.internal:3000'
    );
  });

  it('rewrites 127.0.0.1 to host.docker.internal on darwin', () => {
    expect(translateLocalhostForContainer('http://127.0.0.1:3000', 'darwin')).toBe(
      'http://host.docker.internal:3000'
    );
  });

  it('preserves the path and query string', () => {
    expect(translateLocalhostForContainer('http://localhost:3000/v2?x=1', 'darwin')).toBe(
      'http://host.docker.internal:3000/v2?x=1'
    );
  });

  it('does NOT translate on linux — host.docker.internal does not resolve there by default', () => {
    expect(translateLocalhostForContainer('http://localhost:3000', 'linux')).toBe(
      'http://localhost:3000'
    );
    expect(translateLocalhostForContainer('http://127.0.0.1:3000', 'linux')).toBe(
      'http://127.0.0.1:3000'
    );
  });

  it('leaves non-loopback hosts alone on darwin', () => {
    expect(translateLocalhostForContainer('http://api.internal:3000', 'darwin')).toBe(
      'http://api.internal:3000'
    );
    expect(translateLocalhostForContainer('https://crawlee-cloud.example.com', 'darwin')).toBe(
      'https://crawlee-cloud.example.com'
    );
  });

  it('returns the input unchanged when it is not a valid URL', () => {
    // Defensive: bad input shouldn't crash the runner — caller will surface
    // the underlying URL parse error when it tries to use the value.
    expect(translateLocalhostForContainer('not a url', 'darwin')).toBe('not a url');
  });
});
