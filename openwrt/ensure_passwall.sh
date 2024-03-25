#!/bin/sh


check_node_availability() {
    local url=$1
    response=$(curl -s -I "$url")
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
    return "$success_count"
}

while :
do
    success_count=$(check_url)
    if [ "$success_count" -ne 3 ]; then
        echo "Restarting passwall"
        /etc/init.d/passwall restart
    fi
    sleep 600
done
