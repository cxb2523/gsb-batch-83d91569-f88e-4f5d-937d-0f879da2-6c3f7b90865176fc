import assert from "node:assert/strict";
import test from "node:test";
import {
  CLI_LANGUAGES,
  CLI_MESSAGE_KEYS,
  cliTextForLanguage,
  resolveCliLanguage,
} from "../src/cli-locale.mjs";

const expectedLanguages = ["de", "en", "es", "fr", "it", "ja", "pt", "ru", "zh"];

test("resolves Unix locale precedence and the LANGUAGE priority list", () => {
  assert.equal(resolveCliLanguage({
    env: { LANGUAGE: "fr_FR", LC_ALL: "C.UTF-8", LANG: "fr_FR.UTF-8" },
    defaultLocale: "de-DE",
  }), "en");
  assert.equal(resolveCliLanguage({
    env: { LANGUAGE: "fr_FR", LC_ALL: "POSIX", LANG: "fr_FR.UTF-8" },
    defaultLocale: "de-DE",
  }), "en");
  assert.equal(resolveCliLanguage({
    env: { LANGUAGE: "ko_KR:ja_JP", LANG: "de_DE.UTF-8" },
    defaultLocale: "en-US",
  }), "ja");
  assert.equal(resolveCliLanguage({
    env: { LANGUAGE: "ko_KR", LC_MESSAGES: "de_DE.UTF-8", LANG: "es_ES.UTF-8" },
    defaultLocale: "en-US",
  }), "de");
  assert.equal(resolveCliLanguage({
    env: { LC_ALL: "es_MX.UTF-8", LC_MESSAGES: "de_DE.UTF-8", LANG: "fr_FR.UTF-8" },
    defaultLocale: "en-US",
  }), "es");
});

test("uses the system locale when Unix locale variables are unavailable", () => {
  assert.equal(resolveCliLanguage({ env: {}, defaultLocale: "pt-BR" }), "pt");
  assert.equal(resolveCliLanguage({ env: {}, defaultLocale: "ko-KR" }), "en");
  assert.equal(resolveCliLanguage({ env: {}, defaultLocale: "constructor" }), "en");
  assert.equal(resolveCliLanguage({ env: { LANG: "und" }, defaultLocale: "ja-JP" }), "ja");
  assert.equal(resolveCliLanguage({ env: { LANGUAGE: "und:ja", LANG: "de_DE.UTF-8" }, defaultLocale: "en-US" }), "ja");
});

test("provides every CLI message in every supported language", () => {
  assert.deepEqual(CLI_LANGUAGES, expectedLanguages);
  assert.ok(CLI_MESSAGE_KEYS.length > 0);

  for (const language of CLI_LANGUAGES) {
    for (const key of CLI_MESSAGE_KEYS) {
      const message = cliTextForLanguage(language, key, "value", 2);
      assert.equal(typeof message, "string");
      assert.ok(message.length > 0, `${language}.${key} must not be empty`);
      assert.notEqual(message, key, `${language}.${key} must be translated`);
      if (language !== "en") {
        assert.notEqual(message, cliTextForLanguage("en", key, "value", 2), `${language}.${key} must not fall back to English`);
      }
    }
  }
});

test("falls back safely for unknown languages and message keys", () => {
  assert.equal(cliTextForLanguage("ko-KR", "localOnly"), cliTextForLanguage("en", "localOnly"));
  assert.equal(cliTextForLanguage("fr", "unknownKey"), "unknownKey");
  assert.equal(cliTextForLanguage("fr", "__proto__"), "__proto__");
});
