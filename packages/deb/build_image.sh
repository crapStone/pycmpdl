#!/bin/sh

NAME=packaging-ubuntu

sudo docker rm $NAME
sudo docker rmi $NAME
sudo docker build . -t $NAME
sudo docker run -v $PWD/data:/package -w /package --name $NAME -h $NAME -it $NAME

