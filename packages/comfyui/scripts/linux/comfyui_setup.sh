# ./docker_setup.sh

mkdir -p "$HOME/git"
cd "$HOME/git"

git clone https://github.com/xwzliang/comfyui.git

cd comfyui

docker compose up -d
