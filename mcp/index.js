#!/usr/bin/env node
// getregdata MCP server - exposes the regdata official business-registry actors as MCP tools.
// KYC/AML, credit-risk, due-diligence and B2B data across Europe, the US, UAE,
// Africa and LatAm. Fleet size is derived from actors.js - never hardcode it here
// (see scripts/check-counts.mjs for why).
//
// Auth: set APIFY_TOKEN in the environment (get one free at
// https://apify.com?fpr=getregdata - includes $5 credits).
//
// Run: npx getregdata-mcp   (or: node index.js)
//
// Long-run handling, tool schemas and dispatch live in ./lib.js so they can be
// tested against a fake Apify (npm test). This file is only the stdio entry point.

import { startServer } from "./lib.js";

await startServer();
