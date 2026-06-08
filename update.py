from os import path as ospath, environ
from subprocess import run as srun
from requests import get as rget
from dotenv import load_dotenv
from config import logger
CONFIG_FILE_URL = environ.get('CONFIG_FILE_URL')
try:
    if len(CONFIG_FILE_URL) == 0:
        raise TypeError
    try:
        res = rget(CONFIG_FILE_URL)
        if res.status_code == 200:
            with open('config.env', 'wb+') as f:
                f.write(res.content)
        else:
            logger.error(f"Failed to download config.env {res.status_code}")
    except Exception as e:
        logger.error(f"CONFIG_FILE_URL: {e}")
except:
    pass

load_dotenv('config.env', override=True)

UPSTREAM_REPO = environ.get('UPSTREAM_REPO', '')
if len(UPSTREAM_REPO) == 0:
    UPSTREAM_REPO = "https://github.com/nirajulislam/index"

GITHUB_TOKEN = environ.get('GITHUB_TOKEN', '')
if GITHUB_TOKEN and 'github.com' in UPSTREAM_REPO:
    if 'https://' in UPSTREAM_REPO:
        UPSTREAM_REPO = UPSTREAM_REPO.replace('https://', f'https://{GITHUB_TOKEN}@')
    else:
        UPSTREAM_REPO = f'https://{GITHUB_TOKEN}@{UPSTREAM_REPO.replace("http://", "")}'

UPSTREAM_BRANCH = environ.get('UPSTREAM_BRANCH', '')
if len(UPSTREAM_BRANCH) == 0:
    UPSTREAM_BRANCH = 'main'

if ospath.exists('.git'):
    srun(["rm", "-rf", ".git"])

update = srun([f"git init -q \
                 && git config --global user.email nirajulislam@gmail.com \
                 && git config --global user.name nirajulislam \
                 && git add . \
                 && git commit -sm update -q \
                 && git remote add origin {UPSTREAM_REPO} \
                 && git fetch origin -q \
                 && git reset --hard origin/{UPSTREAM_BRANCH} -q"], shell=True)

if update.returncode == 0:
    logger.info('Successfully updated with latest commit from UPSTREAM_REPO')
else:
    logger.error('Something went wrong while updating, check UPSTREAM_REPO if valid or not!')
