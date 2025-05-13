sudo apt install -y openssh-server tmux git git-lfs
bash ./install_packages/conda_install.sh

bash ./setup_packages/dir_setup.sh
bash ./setup_packages/git_setup.sh

cd ~/git

git clone https://github.com/xwzliang/dotfiles.git

bash ~/git/dotfiles/install.sh

git lfs install
