#!/bin/sh

NAME=packaging-ubuntu

sudo docker start $NAME
sudo docker exec $NAME ./build.sh
sudo docker stop $NAME

