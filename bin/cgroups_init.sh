#!/bin/bash
if ! [ -x "$(command -v cgcreate)" ]; then
  echo 'Error: Cannot find the command cgcreate.' >&2
  echo 'You should have libcgroup-tools installed.' >&2
  exit 1
fi

# should move to config file
CG_USER=nobody
CG_GROUP=nogroup
CG_NAME=sandbox
CG_CTRLS=memory
JUDGE_TMPFS_PATH=/run/shm/judge

echo "Creating memory control group '${CG_NAME}' for ${CG_USER}:${CG_GROUP}..."
sudo cgcreate -t ${CG_USER}:${CG_GROUP} -a ${CG_USER}:${CG_GROUP} -g ${CG_CTRLS}:${CG_NAME}
