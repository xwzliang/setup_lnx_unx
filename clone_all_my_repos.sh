git_path=$HOME/git
mkdir -p $git_path
cd $git_path

CNTX=users  # CNTX should be users or orgs (for organization)
NAME=xwzliang
PAGE=1  # page number

curl "https://api.github.com/$CNTX/$NAME/repos?page=$PAGE&per_page=100" |
  grep -e 'clone_url*' |
  cut -d \" -f 4 |
  xargs -L1 git clone