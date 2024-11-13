xcode-select --install

pip install --pre torch torchvision torchaudio --extra-index-url https://download.pytorch.org/whl/nightly/cpu

python verify.py

cd $HOME/git/Downloads/
git clone https://github.com/comfyanonymous/ComfyUI.git

cd ComfyUI

pip install -r requirements.txt
