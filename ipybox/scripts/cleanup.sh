#!/bin/bash

if [ $# -eq 0 ]; then
    echo "Error: Please provide container ancestor as argument"
    echo "Usage: $0 <ancestor-name>"
    exit 1
fi

docker rm -f $(docker ps -a --filter ancestor="$1" -q)
