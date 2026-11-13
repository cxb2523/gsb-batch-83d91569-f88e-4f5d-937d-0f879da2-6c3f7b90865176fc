# Sourced by preflight.sh, plugin.sh and the desks actions so every entry point finds the same node.
# herdr may run us with a minimal PATH; append the usual install locations (Homebrew, ~/.local, nvm).
PATH="$PATH:/opt/homebrew/bin:/usr/local/bin:$HOME/.local/bin${NVM_BIN:+:$NVM_BIN}:$HOME/.nvm/current/bin"
if ! command -v node >/dev/null 2>&1 && [ -d "$HOME/.nvm/versions/node" ]; then
  for d in "$HOME"/.nvm/versions/node/*/bin; do [ -x "$d/node" ] && NVM_LATEST="$d"; done
  [ -n "${NVM_LATEST:-}" ] && PATH="$PATH:$NVM_LATEST"
fi
export PATH
