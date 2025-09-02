#!/bin/bash

set -e

# Step 1: Install perfSONAR Toolkit
curl -s https://downloads.perfsonar.net/install | sudo sh -s - testpoint 
curl -s https://downloads.perfsonar.net/install | sudo sh -s - archive 

apt install -y perfsonar-grafana perfsonar-grafana-toolkit perfsonar-psconfig-hostmetrics perfsonar-psconfig-publisher
