#!/bin/bash
set -e

script_dir="$(cd "$(dirname "$0")" && pwd)"

# Detect IP type
if ping6 -c 1 google.com &> /dev/null; then
    man_ip_type=ipv6
else
    man_ip_type=ipv4
fi

# Auto-detect OS and VERSION
source /etc/os-release
OS_ID=$ID
OS_VERSION_ID=$VERSION_ID
echo "Detected OS: $OS_ID $OS_VERSION_ID"

# Normalize OS label
if [[ $OS_ID == "ubuntu" ]]; then
    os_label="ubuntu_${OS_VERSION_ID%%.*}"
elif [[ $OS_ID == "rocky" ]]; then
    os_label="rocky_${OS_VERSION_ID%%.*}"
else
    echo "Unsupported OS: $OS_ID"
    exit 1
fi

# Define shared steps
setup_docker_config() {
    sudo mkdir -p /etc/docker
    sudo cp "${script_dir}/docker/daemon.json" /etc/docker/daemon.json
}

add_user_to_docker() {
    local user=$1
    sudo usermod -aG docker "$user"
}

# OS-specific installation
case $os_label in
    ubuntu_20)
        sudo apt-get update
        sudo apt-get install -y apt-transport-https ca-certificates curl software-properties-common
        curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo apt-key add -
        sudo add-apt-repository "deb [arch=amd64] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable"
        sudo apt-get update
        #setup_docker_config
        sudo apt-get install -y docker-ce
        add_user_to_docker ubuntu
        sudo apt-get install -y build-essential zlib1g-dev libncurses5-dev libgdbm-dev libnss3-dev libssl-dev libreadline-dev libffi-dev wget python3.9 python3.9-full tcpdump iftop python3-pip
        python3.9 -m pip install docker rpyc --user
        ;;
    ubuntu_22)
        sudo apt-get update
        sudo apt-get install -y apt-transport-https ca-certificates curl software-properties-common
        curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo apt-key add -
        sudo add-apt-repository "deb [arch=amd64] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable"
        sudo apt-get update
        #setup_docker_config
        sudo apt-get install -y docker-ce docker-ce-cli containerd.io
        add_user_to_docker ubuntu
        sudo apt-get install -y build-essential checkinstall libncursesw5-dev libssl-dev libsqlite3-dev tk-dev libgdbm-dev libc6-dev libbz2-dev wget tcpdump iftop python3-pip
        python3 -m pip install docker rpyc --user
        ;;
    ubuntu_24)
        export DEBIAN_FRONTEND=noninteractive
        sudo apt-get update -y
        sudo apt-get install -y apt-transport-https ca-certificates curl software-properties-common gnupg lsb-release
        curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /usr/share/keyrings/docker-archive-keyring.gpg
        echo "deb [arch=amd64 signed-by=/usr/share/keyrings/docker-archive-keyring.gpg] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" | \
            sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
        sudo apt-get update -y
        #setup_docker_config
        sudo apt-get install -y docker-ce docker-ce-cli containerd.io
        add_user_to_docker ubuntu
        sudo apt-get install -y build-essential checkinstall libncursesw5-dev libssl-dev libsqlite3-dev \
            tk-dev libgdbm-dev libc6-dev libbz2-dev wget tcpdump iftop python3-pip
        python3 -m pip install docker rpyc --user --break-system-packages
        ;;
    rocky_8)
        sudo dnf install -y epel-release
        sudo dnf config-manager --add-repo=https://download.docker.com/linux/centos/docker-ce.repo
        sudo dnf install -y docker-ce docker-ce-cli containerd.io
        #setup_docker_config
        sudo systemctl start docker
        add_user_to_docker rocky
        sudo dnf install -y https://repos.fedorapeople.org/repos/openstack/openstack-yoga/rdo-release-yoga-1.el8.noarch.rpm
        sudo dnf install -y libibverbs tcpdump net-tools python3.9 vim iftop
        pip3.9 install docker rpyc --user
        sudo sysctl --system
        sudo firewall-cmd --zone=public --add-port=5201/tcp --permanent
        sudo firewall-cmd --zone=public --add-port=5201/udp --permanent
        sudo firewall-cmd --reload
        ;;
    rocky_9)
        sudo dnf install -y epel-release
        sudo dnf config-manager --add-repo=https://download.docker.com/linux/centos/docker-ce.repo
        sudo dnf install -y docker-ce docker-ce-cli containerd.io
        #setup_docker_config
        sudo systemctl start docker
        add_user_to_docker rocky
        sudo dnf install -y libibverbs tcpdump net-tools python vim iftop
        pip3.9 install docker rpyc --user
        sudo sysctl --system
        sudo firewall-cmd --zone=public --add-port=5201/tcp --permanent
        sudo firewall-cmd --zone=public --add-port=5201/udp --permanent
        sudo firewall-cmd --reload
        ;;
    *)
        echo "Unsupported or unrecognized OS version: $os_label"
        exit 1
        ;;
esac

echo "Setup complete for $os_label"
