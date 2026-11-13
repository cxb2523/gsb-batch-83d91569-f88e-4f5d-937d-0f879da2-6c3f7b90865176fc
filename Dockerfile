FROM node:24-alpine
WORKDIR /app
ENV NODE_ENV=production HOST=0.0.0.0 PORT=8080
# Build on the host first. No source dataset, .env or provider key enters this context.
COPY --chown=node:node package.json ./
COPY --chown=node:node LICENSE THIRD_PARTY_NOTICES.md ./
COPY --chown=node:node third_party/ ./third_party/
COPY --chown=node:node scripts/serve.mjs ./scripts/serve.mjs
COPY --chown=node:node scripts/lib/key.mjs ./scripts/lib/key.mjs
COPY --chown=node:node scripts/lib/request-guard.mjs scripts/lib/upstream-guard.mjs ./scripts/lib/
COPY --chown=node:node dist/ ./dist/
USER node
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s CMD node -e "fetch('http://127.0.0.1:8080/api/health').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"
CMD ["node", "scripts/serve.mjs"]
