#!/bin/bash

set -e

# Step 1: Install perfSONAR testpoint
curl -s https://downloads.perfsonar.net/install | sudo sh -s - testpoint 
