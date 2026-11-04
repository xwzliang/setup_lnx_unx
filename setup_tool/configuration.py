"""Small, repeatable configuration recipes that preserve existing settings."""
from pathlib import Path
import shutil
import subprocess

from .catalog import SetupError
from .managers import capture

GIT_ALIASES = {"co": "checkout", "ci": "commit", "br": "branch", "st": "status",
               "unstage": "reset HEAD", "last": "log -1"}
TPM_URL = "https://github.com/tmux-plugins/tpm"
VIM_FILETYPES = '''" Managed by setup_lnx_unx: filetypes for shell, Python, and Bats.
augroup setup_lnx_unx_filetypes
  autocmd!
  autocmd BufRead,BufNewFile *.sh,*.bats setfiletype sh
  autocmd BufRead,BufNewFile *.py setfiletype python
augroup END
'''


def describe(recipe):
    if recipe == "git-aliases":
        return [f"git config --global alias.{key} '{value}' (only if absent)"
                for key, value in GIT_ALIASES.items()]
    if recipe == "tmux-plugins":
        return [f"git clone {TPM_URL} ~/.tmux/plugins/tpm (only if absent)",
                "Add the TPM run line to your tmux.conf yourself after reviewing its README."]
    return ["Create ~/.vim/ftdetect/setup_lnx_unx.vim; refuse to overwrite different contents."]


def configure(recipe):
    if recipe == "tmux-plugins":
        if not shutil.which("git"):
            raise SetupError("git is required to fetch the Tmux Plugin Manager")
        path = Path.home() / ".tmux/plugins/tpm"
        if path.exists() or path.is_symlink():
            if not path.is_symlink() and (path / ".git").is_dir():
                result = capture(["git", "-C", str(path), "remote", "get-url", "origin"])
                if result.returncode == 0 and result.stdout.strip().removesuffix(".git") == TPM_URL:
                    print(f"Already configured: {path}")
                    return
            raise SetupError(f"Existing TPM path is not the expected checkout; reconcile manually: {path}")
        path.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "clone", TPM_URL, str(path)], check=True)
        return
    if recipe == "git-aliases":
        if not shutil.which("git"):
            raise SetupError("git is required; install it first")
        pending = []
        for key, value in GIT_ALIASES.items():
            result = capture(["git", "config", "--global", "--get-all", f"alias.{key}"])
            if result.returncode == 0:
                print(f"Preserving existing alias.{key}")
            elif result.returncode == 1:
                pending.append((key, value))
            else:
                raise SetupError(f"Cannot read git config: {result.stderr.strip()}")
        for key, value in pending:
            subprocess.run(["git", "config", "--global", f"alias.{key}", value], check=True)
        return
    path = Path.home() / ".vim/ftdetect/setup_lnx_unx.vim"
    if path.is_symlink():
        raise SetupError(f"Refusing to write through symlink: {path}")
    if path.exists():
        if path.read_text() != VIM_FILETYPES:
            raise SetupError(f"Existing configuration differs; reconcile manually: {path}")
        print(f"Already configured: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as target:
        target.write(VIM_FILETYPES)
    print(f"Created {path}")
