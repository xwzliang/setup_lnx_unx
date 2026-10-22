#!/usr/bin/env bash
set -euo pipefail
# Fisher's current install interface: https://github.com/jorgebucaran/fisher
fish <<'FISH'
if not functions -q fisher
    set -l bootstrap (mktemp)
    curl -fL https://raw.githubusercontent.com/jorgebucaran/fisher/main/functions/fisher.fish -o $bootstrap; or exit 1
    source $bootstrap; or exit 1
    rm -f $bootstrap
    fisher install jorgebucaran/fisher; or exit 1
end
for plugin in jorgebucaran/nvm.fish jethrokuan/z
    if not fisher list | string match -q -- $plugin
        fisher install $plugin; or exit 1
    end
end
FISH
