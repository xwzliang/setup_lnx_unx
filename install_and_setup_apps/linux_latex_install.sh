#!/usr/bin/env bash

apps_to_install=(
    texlive-latex-base		# TeX Live: LaTeX fundamental packages, including pdflatex
    texlive-latex-extra		# TeX Live: LaTeX additional packages
    texlive-fonts-recommended
    # texlive-fonts-extra		# large font package
    texlive-lang-italian	# For LaTeX Error: File `layaureo.sty' not found.
    texlive-xetex			# Packages for XeTeX, the Unicode/OpenType-enabled TeX
)

for app in "${apps_to_install[@]}"; do
    PKG_OK=$(dpkg-query -W --showformat='${Status}\n' $app | grep "install ok installed")
    if [ "" == "$PKG_OK" ]; then
        echo -e "${app} not installed, will install it\n"
        sudo apt install -y ${app}
    else
        echo -e "${app} already installed, will skip it"
    fi
done
