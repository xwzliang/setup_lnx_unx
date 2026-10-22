#!/bin/sh

check_node_availability() {
    local url=$1
    response=$(curl -s -I --connect-timeout 2 "$url")
    if echo "$response" | grep -q "200 OK"; then
        echo "$url is accessible"
        return 0
    else
        echo "$url is not accessible"
        return 1
    fi
}

check_url() {
    success_count=0
    for _ in 1 2 3
    do
        if check_node_availability "https://github.com"; then
            success_count=$((success_count + 1))
        fi
        wait
        sleep 3
    done
    return $success_count
}

while :
do
    check_url
    success_count=$? # Capture the echoed value here
    echo "success count $success_count"
    if [ ! "$success_count" = "3" ]; then
        echo "Restarting passwall"
        /etc/init.d/passwall restart
    fi
    echo "sleeping"
    sleep 300
done
